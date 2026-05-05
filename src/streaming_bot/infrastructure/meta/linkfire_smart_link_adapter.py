"""``LinkfireSmartLinkAdapter`` + ``SelfHostedSmartLinkAdapter``.

Implementaciones de ``ISmartLinkProvider``:

- ``LinkfireSmartLinkAdapter``: API REST de Linkfire (paid) para crear links
  con landing page bonita + tracking nativo.
- ``SelfHostedSmartLinkAdapter``: fallback HTTP propio. Crea entradas en una
  tabla en memoria/persistencia y emite eventos de click. La URL publica es
  ``https://link.<dominio>/{short_id}``; el redirect 302 lo hace un servicio
  separado (FastAPI + SQL).

Ambos adaptadores respetan el contrato ``ISmartLinkProvider``. La eleccion
se hace por config (Linkfire si hay api_key, self-hosted si no).
"""

from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from streaming_bot.domain.meta.smart_link import SmartLink
from streaming_bot.domain.ports.smart_link_provider import (
    ClickEvent,
    ISmartLinkProvider,
    SmartLinkProviderError,
)
from streaming_bot.domain.value_objects import Country

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger


_SHORT_ID_ALPHABET = string.ascii_letters + string.digits
_SHORT_ID_LEN = 8


def _generate_short_id() -> str:
    """Genera un slug aleatorio URL-safe (8 chars)."""
    return "".join(secrets.choice(_SHORT_ID_ALPHABET) for _ in range(_SHORT_ID_LEN))


class LinkfireSmartLinkAdapter(ISmartLinkProvider):
    """Adapter Linkfire (https://linkfire.com). API REST.

    Endpoint: POST /api/links con body ``{name, channelData: [...], links: [...]}``.
    El plan paid devuelve un ``url`` con slug ya generado por Linkfire.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.linkfire.com",
        http_client: httpx.AsyncClient | None = None,
        request_timeout_seconds: float = 30.0,
        logger: BoundLogger | None = None,
    ) -> None:
        if not api_key:
            raise SmartLinkProviderError("linkfire api_key vacia")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=request_timeout_seconds)
        self._timeout = request_timeout_seconds
        self._log: BoundLogger = logger or structlog.get_logger("meta.linkfire")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def create_link(
        self,
        *,
        track_uri: str,
        target_dsps: dict[Country, dict[str, str]],
        slug_hint: str | None = None,
    ) -> SmartLink:
        payload: dict[str, Any] = {
            "name": f"streaming-bot-{track_uri}",
            "trackUri": track_uri,
            "targets": [
                {
                    "country": country.value,
                    "links": [{"dsp": dsp, "url": url} for dsp, url in dsps.items()],
                }
                for country, dsps in target_dsps.items()
            ],
        }
        if slug_hint:
            payload["slug"] = slug_hint

        try:
            response = await self._http.post(
                f"{self._base_url}/api/links",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise SmartLinkProviderError(f"linkfire request fallo: {exc}") from exc
        if response.status_code >= 400:
            raise SmartLinkProviderError(
                f"linkfire status={response.status_code} body={response.text[:200]}",
            )

        data = response.json()
        short_id = str(data.get("slug") or data.get("id") or _generate_short_id())
        self._log.info("linkfire.created", short_id=short_id, track_uri=track_uri)
        return SmartLink(short_id=short_id, target_dsps=target_dsps, track_uri=track_uri)

    async def get_link(self, *, short_id: str) -> SmartLink | None:
        try:
            response = await self._http.get(
                f"{self._base_url}/api/links/{short_id}",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise SmartLinkProviderError(f"linkfire request fallo: {exc}") from exc
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise SmartLinkProviderError(
                f"linkfire status={response.status_code} body={response.text[:200]}",
            )

        data = response.json()
        return self._parse_link(data)

    async def track_click(self, event: ClickEvent) -> None:
        # Linkfire trackea internamente; este metodo es no-op para no
        # duplicar eventos. Se mantiene para cumplir el contrato.
        self._log.debug(
            "linkfire.track_click.noop",
            short_id=event.short_id,
            country=event.country.value if event.country else None,
        )

    @staticmethod
    def _parse_link(data: dict[str, Any]) -> SmartLink:
        targets_data = data.get("targets") or []
        target_dsps: dict[Country, dict[str, str]] = {}
        for target in targets_data:
            country_code = str(target.get("country", "")).upper()
            try:
                country = Country(country_code)
            except ValueError:
                continue
            links: dict[str, str] = {}
            for link in target.get("links", []):
                dsp = str(link.get("dsp", ""))
                url = str(link.get("url", ""))
                if dsp and url:
                    links[dsp] = url
            if links:
                target_dsps[country] = links
        if not target_dsps:
            raise SmartLinkProviderError(f"linkfire devolvio link sin targets: {data}")
        return SmartLink(
            short_id=str(data.get("slug") or data.get("id") or ""),
            target_dsps=target_dsps,
            track_uri=str(data.get("trackUri", "")),
        )


class SelfHostedSmartLinkAdapter(ISmartLinkProvider):
    """Fallback self-hosted: persistencia en memoria + log de clicks.

    Pensado para entornos sin Linkfire. La URL publica
    ``https://link.<dominio>/{short_id}`` la sirve un endpoint FastAPI
    aparte que consulta esta misma estructura (compartida via DB en prod).
    En v1 mantenemos un dict in-memory para que el orchestrator pueda
    operar end-to-end sin red.
    """

    def __init__(
        self,
        *,
        base_url: str,
        logger: BoundLogger | None = None,
    ) -> None:
        if not base_url:
            raise SmartLinkProviderError("self_hosted base_url vacia")
        self._base_url = base_url.rstrip("/")
        self._links: dict[str, SmartLink] = {}
        self._clicks: list[ClickEvent] = []
        self._log: BoundLogger = logger or structlog.get_logger("meta.self_hosted_link")

    @property
    def base_url(self) -> str:
        return self._base_url

    async def create_link(
        self,
        *,
        track_uri: str,
        target_dsps: dict[Country, dict[str, str]],
        slug_hint: str | None = None,
    ) -> SmartLink:
        short_id = (slug_hint or _generate_short_id()).strip()
        if not short_id:
            short_id = _generate_short_id()
        if short_id in self._links:
            existing = self._links[short_id]
            if existing.track_uri == track_uri:
                return existing
            short_id = _generate_short_id()
        link = SmartLink(
            short_id=short_id,
            target_dsps=target_dsps,
            track_uri=track_uri,
        )
        self._links[short_id] = link
        self._log.info(
            "self_hosted.created",
            short_id=short_id,
            track_uri=track_uri,
            countries=[c.value for c in target_dsps],
        )
        return link

    async def get_link(self, *, short_id: str) -> SmartLink | None:
        return self._links.get(short_id)

    async def track_click(self, event: ClickEvent) -> None:
        self._clicks.append(event)
        self._log.info(
            "self_hosted.track_click",
            short_id=event.short_id,
            country=event.country.value if event.country else None,
            dsp=event.dsp_target,
        )

    def clicks_for(self, short_id: str) -> list[ClickEvent]:
        """Helper para tests / inspeccion local."""
        return [c for c in self._clicks if c.short_id == short_id]

    @staticmethod
    def now_utc() -> datetime:
        """Util para que el caller construya ``ClickEvent`` con UTC consistente."""
        return datetime.now(UTC)
