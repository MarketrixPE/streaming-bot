"""Implementacion de `ISoundcloudClient` contra `api-v2.soundcloud.com`.

SoundCloud no expone una API REST publica versionada; la app web usa
`api-v2.soundcloud.com` y autentica cada request con un `client_id`
embebido en uno de los bundles JS que sirve la homepage. El cliente:

1. Scrapea `https://soundcloud.com/` la primera vez para localizar todos
   los bundles `<script src=".../assets/...js">` y busca un `client_id`
   con regex `client_id=([a-zA-Z0-9]{20,})`.
2. Cachea el `client_id` por 24h. Si recibe 401 lo invalida y refresca.
3. Implementa rate-limit interno (semaforo + delay configurable) para
   no provocar bloqueos del WAF.
4. Cachea metadata de tracks por 5 minutos (TTL configurable) para no
   pegar dos veces al mismo URN dentro de una misma sesion.

El cliente NO maneja login (los endpoints write requieren bearer de
sesion humana, esos van por la strategy Patchright).
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any

import httpx

from streaming_bot.domain.exceptions import TargetSiteError, TransientError
from streaming_bot.domain.ports.soundcloud_client import ISoundcloudClient
from streaming_bot.domain.soundcloud.models import SoundcloudTrack, SoundcloudUser

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# Constantes de transporte: la base URL de la API privada y la pagina
# desde la que extraemos el client_id.
_API_BASE = "https://api-v2.soundcloud.com"
_HOMEPAGE = "https://soundcloud.com/"

# Regex para extraer el client_id de los bundles JS. SoundCloud lo expone
# como `client_id:"XXXX"` o `client_id=XXXX` segun el bundle. Aceptamos
# ambos para tolerar refactors menores en el frontend.
_CLIENT_ID_REGEX = re.compile(r'client_id\s*[:=]\s*"?([a-zA-Z0-9]{20,})"?')

# Regex para extraer URLs de scripts de la homepage. SoundCloud sirve
# bundles desde `https://a-v2.sndcdn.com/assets/...js`.
_SCRIPT_SRC_REGEX = re.compile(r'<script[^>]+src="([^"]+\.js)"')

# TTL del client_id (24h en s) y de la metadata de tracks (5min en s).
_CLIENT_ID_TTL_S = 24 * 60 * 60
_TRACK_CACHE_TTL_S = 5 * 60


class SoundcloudClientError(TargetSiteError):
    """Error tipado para fallas del cliente SoundCloud v2."""


@dataclass(slots=True)
class _CachedClientId:
    """Entrada de cache del client_id (valor + monotonic timestamp)."""

    value: str
    expires_at_monotonic: float


@dataclass(slots=True)
class _CachedTrack:
    """Entrada de cache de track (DTO + monotonic timestamp)."""

    track: SoundcloudTrack
    expires_at_monotonic: float


class SoundcloudV2Client(ISoundcloudClient):
    """Cliente READ contra la API privada v2 de SoundCloud."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        request_timeout_s: float = 10.0,
        rate_limit_delay_ms: int = 200,
        client_id_ttl_s: int = _CLIENT_ID_TTL_S,
        track_cache_ttl_s: int = _TRACK_CACHE_TTL_S,
    ) -> None:
        self._http_client = http_client
        self._owned_client = http_client is None
        self._request_timeout_s = request_timeout_s
        self._rate_limit_delay_ms = rate_limit_delay_ms
        self._client_id_ttl_s = client_id_ttl_s
        self._track_cache_ttl_s = track_cache_ttl_s
        # Lock asincrono para serializar el scraping inicial del client_id.
        self._client_id_lock = asyncio.Lock()
        self._cached_client_id: _CachedClientId | None = None
        self._track_cache: dict[str, _CachedTrack] = {}
        # Semaforo simple para limitar concurrencia: evita rafagas que
        # disparen el WAF. Calibrado conservador.
        self._semaphore = asyncio.Semaphore(4)

    async def __aenter__(self) -> SoundcloudV2Client:
        if self._owned_client:
            self._http_client = httpx.AsyncClient(timeout=self._request_timeout_s)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del exc_type, exc, tb
        await self.async_close()

    async def async_close(self) -> None:
        """Cierra el AsyncClient si lo creamos nosotros."""
        if self._owned_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    # ── ISoundcloudClient ──────────────────────────────────────────────────

    async def get_track(self, track_id_or_urn: str | int) -> SoundcloudTrack | None:
        """Devuelve metadata de un track. None si 404. Cachea 5min."""
        track_id = _coerce_track_id(track_id_or_urn)
        cache_key = str(track_id)
        cached = self._track_cache.get(cache_key)
        if cached is not None and cached.expires_at_monotonic > time.monotonic():
            return cached.track

        try:
            payload = await self._request("GET", f"/tracks/{track_id}")
        except SoundcloudClientError as exc:
            if "404" in str(exc):
                return None
            raise

        track = _track_from_payload(payload)
        self._track_cache[cache_key] = _CachedTrack(
            track=track,
            expires_at_monotonic=time.monotonic() + self._track_cache_ttl_s,
        )
        return track

    async def get_user(self, user_id_or_permalink: str | int) -> SoundcloudUser | None:
        """Devuelve metadata de un usuario por id numerico o permalink slug."""
        if isinstance(user_id_or_permalink, int) or str(user_id_or_permalink).isdigit():
            path = f"/users/{user_id_or_permalink}"
        else:
            path = f"/resolve?url=https://soundcloud.com/{user_id_or_permalink}"
        try:
            payload = await self._request("GET", path)
        except SoundcloudClientError as exc:
            if "404" in str(exc):
                return None
            raise
        if payload.get("kind") not in {None, "user"}:
            return None
        return _user_from_payload(payload)

    async def search_tracks(
        self,
        *,
        query: str,
        limit: int = 20,
    ) -> list[SoundcloudTrack]:
        payload = await self._request(
            "GET",
            "/search/tracks",
            params={"q": query, "limit": min(max(limit, 1), 50)},
        )
        items = payload.get("collection", [])
        return [_track_from_payload(it) for it in items if isinstance(it, dict)]

    async def get_track_plays_count(self, track_id_or_urn: str | int) -> int:
        track = await self.get_track(track_id_or_urn)
        if track is None:
            return 0
        return track.playback_count or 0

    # ── HTTP helpers internos ──────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Envia el request y maneja 401 (refresh client_id) + 4xx/5xx."""
        client = self._require_http_client()
        attempts = 0
        while True:
            attempts += 1
            client_id = await self._ensure_client_id()
            full_params: dict[str, Any] = {"client_id": client_id}
            if params:
                full_params.update(params)
            url = f"{_API_BASE}{path}"
            async with self._semaphore:
                # Rate limit suave entre requests para no saturar el WAF.
                await asyncio.sleep(self._rate_limit_delay_ms / 1000.0)
                try:
                    response = await client.request(method, url, params=full_params)
                except httpx.RequestError as exc:
                    raise TransientError(f"soundcloud request error: {exc}") from exc

            if response.status_code == 401 and attempts == 1:
                # client_id caducado: invalidamos y reintentamos UNA vez.
                self._cached_client_id = None
                continue
            if response.status_code == 404:
                raise SoundcloudClientError(f"soundcloud 404 {path}")
            if response.status_code >= 500:
                raise TransientError(
                    f"soundcloud {response.status_code} {path}",
                )
            if response.status_code >= 400:
                raise SoundcloudClientError(
                    f"soundcloud {response.status_code} {path}",
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise SoundcloudClientError(f"soundcloud json invalido en {path}") from exc
            if not isinstance(payload, dict):
                # Algunos endpoints (vg /tracks/{id}/comments) devuelven array.
                # Lo envolvemos para que el caller siempre reciba dict.
                return {"collection": payload}
            return payload

    async def _ensure_client_id(self) -> str:
        """Devuelve el client_id valido, scrapeando la homepage si hace falta."""
        cached = self._cached_client_id
        now = time.monotonic()
        if cached is not None and cached.expires_at_monotonic > now:
            return cached.value

        async with self._client_id_lock:
            cached = self._cached_client_id
            now = time.monotonic()
            if cached is not None and cached.expires_at_monotonic > now:
                return cached.value
            client_id = await self._scrape_client_id()
            self._cached_client_id = _CachedClientId(
                value=client_id,
                expires_at_monotonic=now + self._client_id_ttl_s,
            )
            return client_id

    async def _scrape_client_id(self) -> str:
        """Descarga la homepage, identifica los bundles JS y extrae client_id."""
        client = self._require_http_client()
        try:
            home = await client.get(_HOMEPAGE)
        except httpx.RequestError as exc:
            raise TransientError(f"no se pudo cargar homepage soundcloud: {exc}") from exc
        if home.status_code >= 400:
            raise SoundcloudClientError(
                f"homepage soundcloud devolvio {home.status_code}",
            )
        scripts = _SCRIPT_SRC_REGEX.findall(home.text)
        if not scripts:
            raise SoundcloudClientError("no se encontraron bundles js en la homepage")
        async for client_id in self._iter_bundles_for_client_id(scripts):
            return client_id
        raise SoundcloudClientError(
            "no se encontro client_id en ninguno de los bundles js",
        )

    async def _iter_bundles_for_client_id(
        self,
        scripts: list[str],
    ) -> AsyncIterator[str]:
        """Generador async: yield del primer client_id encontrado."""
        client = self._require_http_client()
        for src in scripts:
            try:
                bundle = await client.get(src)
            except httpx.RequestError:
                continue
            if bundle.status_code >= 400:
                continue
            match = _CLIENT_ID_REGEX.search(bundle.text)
            if match:
                yield match.group(1)
                return

    def _require_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            raise SoundcloudClientError(
                "SoundcloudV2Client no inicializado: usar 'async with' o pasar http_client",
            )
        return self._http_client


# ── Helpers puros (mapeo de payloads) ──────────────────────────────────────


def _coerce_track_id(value: str | int) -> int:
    """Convierte URN o id numerico en el id entero que la API espera."""
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    if ":" in text:
        # Formato URN: "soundcloud:tracks:123456"
        last = text.rsplit(":", 1)[-1]
        if last.isdigit():
            return int(last)
    raise ValueError(f"track id invalido: {value!r}")


def _track_from_payload(payload: dict[str, Any]) -> SoundcloudTrack:
    """Mapea un payload de /tracks/{id} a `SoundcloudTrack`."""
    track_id = int(payload["id"])
    user_section = payload.get("user", {}) or {}
    user_id = int(user_section.get("id", payload.get("user_id", 0)))
    return SoundcloudTrack(
        urn=payload.get("urn") or f"soundcloud:tracks:{track_id}",
        track_id=track_id,
        title=str(payload.get("title", "")),
        permalink_url=str(payload.get("permalink_url", "")),
        duration_ms=int(payload.get("duration", 0)),
        user_id=user_id,
        playback_count=_optional_int(payload.get("playback_count")),
        likes_count=_optional_int(payload.get("likes_count")),
        reposts_count=_optional_int(payload.get("reposts_count")),
        comment_count=_optional_int(payload.get("comment_count")),
        monetization_model=payload.get("monetization_model"),
        isrc=(payload.get("publisher_metadata") or {}).get("isrc"),
    )


def _user_from_payload(payload: dict[str, Any]) -> SoundcloudUser:
    """Mapea un payload de /users/{id} (o /resolve) a `SoundcloudUser`."""
    return SoundcloudUser(
        user_id=int(payload["id"]),
        permalink=str(payload.get("permalink", "")),
        username=str(payload.get("username", "")),
        followers_count=int(payload.get("followers_count", 0)),
        country=None,
        verified=bool(payload.get("verified", False)),
    )


def _optional_int(value: Any) -> int | None:
    """Coerce defensivo a `int | None` (algunos endpoints devuelven None)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
