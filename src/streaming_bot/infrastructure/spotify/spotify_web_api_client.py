"""Implementación de ISpotifyClient usando Spotify Web API oficial."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
)

from streaming_bot.domain.ports.spotify_client import (
    ISpotifyClient,
    SpotifyArtistMeta,
    SpotifyPlaylistMeta,
    SpotifyTrackMeta,
)
from streaming_bot.infrastructure.spotify.auth import SpotifyTokenCache
from streaming_bot.infrastructure.spotify.config import SpotifyConfig
from streaming_bot.infrastructure.spotify.errors import SpotifyApiError, SpotifyAuthError

if TYPE_CHECKING:
    from streaming_bot.domain.value_objects import Country

logger = structlog.get_logger("streaming_bot.spotify")


class SpotifyWebApiClient(ISpotifyClient):
    """Cliente HTTP para Spotify Web API con manejo de rate limits y retries."""

    def __init__(
        self,
        config: SpotifyConfig,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._http_client = http_client
        self._owned_client = http_client is None
        self._token_cache: SpotifyTokenCache | None = None
        self._base_url = "https://api.spotify.com/v1"

    async def __aenter__(self) -> SpotifyWebApiClient:
        if self._owned_client:
            self._http_client = httpx.AsyncClient(timeout=self._config.request_timeout_seconds)
        assert self._http_client is not None
        self._token_cache = SpotifyTokenCache(self._config, self._http_client)
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.async_close()

    async def async_close(self) -> None:
        """Cierra el cliente HTTP si es propiedad de esta instancia."""
        if self._owned_client and self._http_client:
            await self._http_client.aclose()

    async def get_track(self, uri: str) -> SpotifyTrackMeta | None:
        track_id = self._extract_id(uri, "track")
        try:
            payload = await self._request("GET", f"/tracks/{track_id}")
        except SpotifyApiError as e:
            if e.status_code == 404:
                return None
            raise
        return self._to_track_meta(payload)

    async def get_tracks_batch(self, uris: list[str]) -> list[SpotifyTrackMeta]:
        if not uris:
            return []

        track_ids = [self._extract_id(uri, "track") for uri in uris]
        results: list[SpotifyTrackMeta] = []

        for i in range(0, len(track_ids), 50):
            chunk = track_ids[i : i + 50]
            payload = await self._request("GET", "/tracks", params={"ids": ",".join(chunk)})
            tracks = payload.get("tracks", [])
            for track in tracks:
                if track is not None:
                    results.append(self._to_track_meta(track))

        return results

    async def get_artist(self, uri: str) -> SpotifyArtistMeta | None:
        artist_id = self._extract_id(uri, "artist")
        try:
            payload = await self._request("GET", f"/artists/{artist_id}")
        except SpotifyApiError as e:
            if e.status_code == 404:
                return None
            raise

        return SpotifyArtistMeta(
            uri=payload["uri"],
            name=payload["name"],
            genres=tuple(payload.get("genres", [])),
            popularity=payload.get("popularity", 0),
            follower_count=payload.get("followers", {}).get("total", 0),
        )

    async def search_tracks(
        self,
        *,
        query: str,
        market: Country | None = None,
        limit: int = 20,
    ) -> list[SpotifyTrackMeta]:
        market_code = (market or self._config.default_market).value
        payload = await self._request(
            "GET",
            "/search",
            params={
                "q": query,
                "type": "track",
                "market": market_code,
                "limit": min(limit, 50),
            },
        )
        tracks = payload.get("tracks", {}).get("items", [])
        return [self._to_track_meta(t) for t in tracks]

    async def get_top_tracks_by_genre(
        self,
        *,
        genre: str,
        market: Country,
        limit: int = 50,
    ) -> list[SpotifyTrackMeta]:
        """Top tracks de un género usando search con field-filter.

        TODO: Spotify deprecó seed_genres en algunos endpoints. Este approach
        usa search con genre:"<genre>", pero podría pivotear a editorial playlist IDs
        (e.g. Top 50 Latam, Top Viral PE) si este método deja de funcionar.
        """
        query = f'genre:"{genre}"'
        return await self.search_tracks(query=query, market=market, limit=limit)

    async def get_artist_top_tracks(
        self,
        *,
        artist_uri: str,
        market: Country,
    ) -> list[SpotifyTrackMeta]:
        artist_id = self._extract_id(artist_uri, "artist")
        payload = await self._request(
            "GET",
            f"/artists/{artist_id}/top-tracks",
            params={"market": market.value},
        )
        tracks = payload.get("tracks", [])
        return [self._to_track_meta(t) for t in tracks]

    async def get_playlist(self, playlist_id: str) -> SpotifyPlaylistMeta | None:
        pid = self._extract_id(playlist_id, "playlist")
        try:
            payload = await self._request("GET", f"/playlists/{pid}")
        except SpotifyApiError as e:
            if e.status_code == 404:
                return None
            raise

        return SpotifyPlaylistMeta(
            uri=payload["uri"],
            spotify_id=payload["id"],
            name=payload["name"],
            description=payload.get("description", ""),
            owner_id=payload["owner"]["id"],
            is_public=payload.get("public", False),
            follower_count=payload.get("followers", {}).get("total", 0),
            track_count=payload.get("tracks", {}).get("total", 0),
        )

    async def get_playlist_tracks(self, playlist_id: str) -> list[SpotifyTrackMeta]:
        pid = self._extract_id(playlist_id, "playlist")
        results: list[SpotifyTrackMeta] = []
        url: str | None = f"/playlists/{pid}/tracks"

        while url:
            if url.startswith("http"):
                parsed = urlparse(url)
                url = parsed.path + (f"?{parsed.query}" if parsed.query else "")

            payload = await self._request("GET", url)
            items = payload.get("items", [])

            for item in items:
                track = item.get("track")
                if track is not None:
                    results.append(self._to_track_meta(track))

            url = payload.get("next")

        return results

    async def create_playlist(
        self,
        *,
        owner_user_id: str,
        name: str,
        description: str = "",
        public: bool = False,
    ) -> SpotifyPlaylistMeta:
        payload = await self._request(
            "POST",
            f"/users/{owner_user_id}/playlists",
            json={"name": name, "description": description, "public": public},
            requires_user_token=True,
        )

        return SpotifyPlaylistMeta(
            uri=payload["uri"],
            spotify_id=payload["id"],
            name=payload["name"],
            description=payload.get("description", ""),
            owner_id=payload["owner"]["id"],
            is_public=payload.get("public", False),
            follower_count=0,
            track_count=0,
        )

    async def add_tracks_to_playlist(
        self,
        *,
        playlist_id: str,
        track_uris: list[str],
    ) -> None:
        if not track_uris:
            return

        pid = self._extract_id(playlist_id, "playlist")

        for i in range(0, len(track_uris), 100):
            chunk = track_uris[i : i + 100]
            await self._request(
                "POST",
                f"/playlists/{pid}/tracks",
                json={"uris": chunk},
                requires_user_token=True,
            )

    async def reorder_playlist_tracks(
        self,
        *,
        playlist_id: str,
        range_start: int,
        insert_before: int,
    ) -> None:
        pid = self._extract_id(playlist_id, "playlist")
        await self._request(
            "PUT",
            f"/playlists/{pid}/tracks",
            json={"range_start": range_start, "insert_before": insert_before},
            requires_user_token=True,
        )

    async def _request(  # noqa: PLR0912, PLR0915
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        requires_user_token: bool = False,
    ) -> dict[str, Any]:
        """Wrapper que maneja auth, rate limits, retries, y errores."""
        assert self._token_cache is not None
        assert self._http_client is not None

        token = await self._token_cache.get_token(requires_user_token=requires_user_token)
        headers = {"Authorization": f"Bearer {token}"}

        url = f"{self._base_url}{path}" if not path.startswith("http") else path
        global_attempt = 0
        refreshed_auth = False

        while global_attempt < self._config.max_retries:
            global_attempt += 1

            try:
                async for retry_attempt in AsyncRetrying(
                    retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
                    stop=stop_after_attempt(1),
                    reraise=True,
                ):
                    with retry_attempt:
                        start_time = time.perf_counter()

                        response = await self._http_client.request(
                            method,
                            url,
                            headers=headers,
                            params=params,
                            json=json,
                        )
                        latency_ms = int((time.perf_counter() - start_time) * 1000)

                        if response.status_code == 429:
                            retry_after = int(response.headers.get("Retry-After", 1))
                            logger.warning(
                                "rate_limited",
                                path=path,
                                retry_after=retry_after,
                                attempt=global_attempt,
                            )
                            await asyncio.sleep(retry_after)
                            continue

                        if response.status_code == 401:
                            logger.warning("unauthorized", path=path, attempt=global_attempt)
                            if not refreshed_auth:
                                await self._token_cache.force_refresh()
                                token = await self._token_cache.get_token(
                                    requires_user_token=requires_user_token
                                )
                                headers = {"Authorization": f"Bearer {token}"}
                                refreshed_auth = True
                                continue
                            raise SpotifyAuthError("Authentication failed after token refresh")

                        if response.status_code in {500, 502, 503, 504}:
                            logger.warning(
                                "server_error",
                                path=path,
                                status=response.status_code,
                                attempt=global_attempt,
                            )
                            if global_attempt < self._config.max_retries:
                                await asyncio.sleep(1.5**global_attempt)
                                continue
                            raise SpotifyApiError(
                                response.status_code,
                                f"Server error after {global_attempt} attempts",
                            )

                        if response.status_code >= 400:
                            body = response.text[:500]
                            logger.error(
                                "api_error",
                                path=path,
                                status=response.status_code,
                                body_snippet=body[:200],
                            )
                            raise SpotifyApiError(response.status_code, body)

                        logger.debug(
                            "request_success",
                            method=method,
                            path=path,
                            status=response.status_code,
                            latency_ms=latency_ms,
                            attempt=global_attempt,
                        )

                        result: dict[str, Any] = response.json()
                        return result

            except httpx.RequestError as e:
                logger.warning(
                    "request_error",
                    path=path,
                    error=str(e),
                    attempt=global_attempt,
                )
                if global_attempt >= self._config.max_retries:
                    raise
                await asyncio.sleep(1.5**global_attempt)
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in {500, 502, 503, 504}:
                    raise
                if global_attempt >= self._config.max_retries:
                    raise
                await asyncio.sleep(1.5**global_attempt)

        raise RuntimeError("Retry logic exhausted")  # pragma: no cover

    @staticmethod
    def _extract_id(uri: str, expected_type: str) -> str:
        """Extrae el ID de una URI de Spotify o valida un ID pelado.

        Args:
            uri: spotify:track:XXXX, spotify:artist:XXXX, o el ID pelado.
            expected_type: "track", "artist", "playlist".

        Returns:
            El ID extraído.

        Raises:
            ValueError: Si la URI es inválida o no coincide con el tipo esperado.
        """
        if uri.startswith("spotify:"):
            parts = uri.split(":")
            if len(parts) != 3 or parts[1] != expected_type:
                raise ValueError(f"Invalid Spotify URI for {expected_type}: {uri}")
            return parts[2]
        return uri

    @staticmethod
    def _to_track_meta(payload: dict[str, Any]) -> SpotifyTrackMeta:
        """Convierte el payload JSON de la API a SpotifyTrackMeta."""
        return SpotifyTrackMeta(
            uri=payload["uri"],
            name=payload["name"],
            duration_ms=payload["duration_ms"],
            artist_uris=tuple(a["uri"] for a in payload.get("artists", [])),
            artist_names=tuple(a["name"] for a in payload.get("artists", [])),
            album_uri=payload.get("album", {}).get("uri", ""),
            popularity=payload.get("popularity", 0),
            explicit=payload.get("explicit", False),
            isrc=payload.get("external_ids", {}).get("isrc"),
        )
