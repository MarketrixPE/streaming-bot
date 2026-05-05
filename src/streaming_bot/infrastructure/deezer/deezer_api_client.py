"""Implementacion `IDeezerClient` basada en httpx.

Dos canales:

1. **API publica** (`api.deezer.com`): metadata de tracks/artistas. No
   requiere autenticacion. Sujeta a rate limits suaves (~50 req/5s/IP).

2. **API privada** (`www.deezer.com/ajax/gw-light.php`): historial de
   usuario y follow_artist. Requiere cookies de sesion (`sid`, `arl`)
   capturadas previamente por Patchright tras un login real. Si las
   cookies no estan configuradas, los metodos privados devuelven
   resultados vacios (history -> None) en lugar de explotar.

El cliente NO mantiene autenticacion propia: las cookies se inyectan en
construccion. Esto mantiene la frontera limpia entre "que browser logueo
la cuenta" (Patchright/Camoufox) y "como hablamos con la API una vez
logueados".

Mock-friendly: se puede inyectar un `httpx.AsyncClient` para tests, y la
implementacion no abre conexiones por su cuenta cuando recibe uno externo.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, cast

import httpx
import structlog

from streaming_bot.domain.deezer.listener_history import DeezerListenerHistory
from streaming_bot.domain.ports.deezer_client import (
    DeezerApiError,
    DeezerArtist,
    DeezerTrack,
    IDeezerClient,
)

logger = structlog.get_logger("streaming_bot.deezer")

_PUBLIC_API_BASE = "https://api.deezer.com"
_PRIVATE_API_BASE = "https://www.deezer.com/ajax/gw-light.php"
_DEFAULT_TIMEOUT_SECONDS = 10.0
_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 0.8


class DeezerApiClient(IDeezerClient):
    """Cliente Deezer asincrono con soporte de canales publico y privado."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        session_cookies: Mapping[str, str] | None = None,
        public_api_base: str = _PUBLIC_API_BASE,
        private_api_base: str = _PRIVATE_API_BASE,
        request_timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        if max_retries < 1:
            raise ValueError(f"max_retries debe ser >= 1: {max_retries}")
        self._http = http_client
        self._owned = http_client is None
        self._cookies = dict(session_cookies) if session_cookies else None
        self._public_base = public_api_base.rstrip("/")
        self._private_base = private_api_base
        self._timeout = request_timeout_seconds
        self._max_retries = max_retries

    async def __aenter__(self) -> DeezerApiClient:
        if self._owned and self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Libera el cliente HTTP solo si lo creamos nosotros."""
        if self._owned and self._http is not None:
            await self._http.aclose()
            self._http = None

    # ── API publica ───────────────────────────────────────────────────────
    async def get_track(self, track_id: int | str) -> DeezerTrack | None:
        normalized = self._normalize_track_id(track_id)
        payload = await self._request_public("GET", f"/track/{normalized}")
        if payload is None:
            return None
        if "error" in payload:
            error = payload.get("error", {})
            if isinstance(error, dict) and error.get("code") == 800:
                return None
            raise DeezerApiError(f"deezer api error: {error}")
        return _to_track(payload)

    async def search_artist(self, query: str, *, limit: int = 10) -> list[DeezerArtist]:
        if not query.strip():
            return []
        payload = await self._request_public(
            "GET",
            "/search/artist",
            params={"q": query, "limit": str(min(max(limit, 1), 50))},
        )
        if payload is None:
            return []
        items = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return []
        return [_to_artist(item) for item in items if isinstance(item, dict)]

    # ── API privada (requiere cookies) ────────────────────────────────────
    async def get_user_history(self, account_id: str) -> DeezerListenerHistory | None:
        if self._cookies is None:
            logger.debug("deezer.history.skip_no_cookies", account_id=account_id)
            return None
        payload = await self._request_private(
            method_name="user.getRecentTracks",
            body={"user_id": account_id, "nb": 200},
        )
        if payload is None:
            return None
        return _to_history(account_id, payload)

    async def follow_artist(self, account_id: str, artist_id: int | str) -> None:
        if self._cookies is None:
            raise DeezerApiError("follow_artist requiere session_cookies; ninguna configurada")
        normalized = self._normalize_artist_id(artist_id)
        payload = await self._request_private(
            method_name="artist.addFavorite",
            body={"user_id": account_id, "artist_id": normalized},
        )
        if payload is None:
            raise DeezerApiError("follow_artist no recibio respuesta")
        error = payload.get("error") if isinstance(payload, dict) else None
        if error:
            raise DeezerApiError(f"follow_artist fallo: {error}")

    # ── Internals: HTTP con retry/backoff ────────────────────────────────
    async def _request_public(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> dict[str, Any] | None:
        url = f"{self._public_base}{path}"
        return await self._send_with_retry(method, url, params=params, body=None, private=False)

    async def _request_private(
        self,
        *,
        method_name: str,
        body: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        params = {
            "method": method_name,
            "input": "3",
            "api_version": "1.0",
            "api_token": "",
        }
        return await self._send_with_retry(
            "POST",
            self._private_base,
            params=params,
            body=dict(body),
            private=True,
        )

    async def _send_with_retry(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None,
        body: Mapping[str, Any] | None,
        private: bool,
    ) -> dict[str, Any] | None:
        client = self._http
        if client is None:
            raise DeezerApiError(
                "DeezerApiClient no tiene httpx.AsyncClient: usar 'async with' "
                "o pasar http_client en el constructor"
            )

        cookies = self._cookies if private else None
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=body if private else None,
                    cookies=cookies,
                    timeout=self._timeout,
                )
            except httpx.RequestError as exc:
                last_exc = exc
                logger.warning(
                    "deezer.request_error",
                    url=url,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt == self._max_retries:
                    raise DeezerApiError(f"transport error contra {url}: {exc}") from exc
                await asyncio.sleep(_BACKOFF_BASE_SECONDS * attempt)
                continue

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "1") or "1")
                logger.warning(
                    "deezer.rate_limited",
                    url=url,
                    retry_after=retry_after,
                    attempt=attempt,
                )
                await asyncio.sleep(retry_after)
                continue

            if response.status_code in {500, 502, 503, 504}:
                if attempt == self._max_retries:
                    raise DeezerApiError(
                        f"server error {response.status_code} agotando reintentos"
                    )
                await asyncio.sleep(_BACKOFF_BASE_SECONDS * attempt)
                continue

            if response.status_code == 404:
                return None

            if response.status_code >= 400:
                raise DeezerApiError(
                    f"http {response.status_code} contra {url}: {response.text[:200]}"
                )

            try:
                parsed = response.json()
            except json.JSONDecodeError as exc:
                raise DeezerApiError(f"respuesta no-JSON desde {url}") from exc
            return cast(dict[str, Any], parsed) if isinstance(parsed, dict) else None

        if last_exc is not None:
            raise DeezerApiError(str(last_exc)) from last_exc
        return None

    # ── Helpers de normalizacion ─────────────────────────────────────────
    @staticmethod
    def _normalize_track_id(track_id: int | str) -> str:
        if isinstance(track_id, int):
            return str(track_id)
        if track_id.startswith("deezer:track:"):
            return track_id.split(":", maxsplit=2)[2]
        return track_id

    @staticmethod
    def _normalize_artist_id(artist_id: int | str) -> str:
        if isinstance(artist_id, int):
            return str(artist_id)
        if artist_id.startswith("deezer:artist:"):
            return artist_id.split(":", maxsplit=2)[2]
        return artist_id


# ── Mappers payload -> domain ────────────────────────────────────────────
def _to_track(payload: Mapping[str, Any]) -> DeezerTrack:
    artist = payload.get("artist", {}) or {}
    album = payload.get("album", {}) or {}
    deezer_id = int(payload.get("id", 0))
    return DeezerTrack(
        uri=f"deezer:track:{deezer_id}",
        deezer_id=deezer_id,
        title=str(payload.get("title", "")),
        duration_seconds=int(payload.get("duration", 0)),
        artist_id=int(artist.get("id", 0)) if isinstance(artist, dict) else 0,
        artist_name=str(artist.get("name", "")) if isinstance(artist, dict) else "",
        album_id=int(album.get("id", 0)) if isinstance(album, dict) else 0,
        album_title=str(album.get("title", "")) if isinstance(album, dict) else "",
        isrc=str(payload["isrc"]) if payload.get("isrc") else None,
    )


def _to_artist(payload: Mapping[str, Any]) -> DeezerArtist:
    deezer_id = int(payload.get("id", 0))
    return DeezerArtist(
        uri=f"deezer:artist:{deezer_id}",
        deezer_id=deezer_id,
        name=str(payload.get("name", "")),
        nb_fans=int(payload.get("nb_fan", 0) or 0),
        nb_albums=int(payload.get("nb_album", 0) or 0),
        picture_url=str(payload["picture_medium"]) if payload.get("picture_medium") else None,
    )


def _to_history(account_id: str, payload: Mapping[str, Any]) -> DeezerListenerHistory:
    """Mapea la respuesta privada `user.getRecentTracks` al dominio.

    El payload real tiene la forma `{"results": {"data": [...], "stats": {...}}}`.
    Aceptamos varias formas defensivas para no romper si Deezer cambia keys
    menores; los campos ausentes se agregan como cero/empty.
    """
    if "results" in payload and isinstance(payload["results"], dict):
        results = cast(Mapping[str, Any], payload["results"])
    else:
        results = payload

    stats_obj = results.get("stats", {}) if isinstance(results, Mapping) else {}
    stats: Mapping[str, Any] = stats_obj if isinstance(stats_obj, Mapping) else {}
    artists_raw = results.get("artists", []) if isinstance(results, Mapping) else []

    artists_followed: tuple[str, ...] = tuple(
        str(item.get("id"))
        for item in artists_raw
        if isinstance(item, Mapping) and item.get("id") is not None
    )

    avg_session_minutes = float(stats.get("avg_session_minutes_30d", 0.0) or 0.0)
    replay_rate = float(stats.get("replay_rate_30d", 0.0) or 0.0)
    distinct_tracks = int(stats.get("distinct_tracks_30d", 0) or 0)
    distinct_albums = int(stats.get("distinct_albums_30d", 0) or 0)

    last_session_iso = stats.get("last_session_at")
    last_session_at: datetime | None = None
    if isinstance(last_session_iso, str) and last_session_iso:
        try:
            last_session_at = datetime.fromisoformat(last_session_iso)
            if last_session_at.tzinfo is None:
                last_session_at = last_session_at.replace(tzinfo=UTC)
        except ValueError:
            last_session_at = None

    return DeezerListenerHistory(
        account_id=account_id,
        artists_followed=artists_followed,
        avg_session_minutes_30d=avg_session_minutes,
        replay_rate=min(max(replay_rate, 0.0), 1.0),
        distinct_tracks_30d=distinct_tracks,
        distinct_albums_30d=distinct_albums,
        last_session_at=last_session_at,
    )
