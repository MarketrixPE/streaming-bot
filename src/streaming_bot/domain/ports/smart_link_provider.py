"""Puerto ``ISmartLinkProvider``: crea y trackea links con geo-routing.

Implementaciones esperadas:
- ``LinkfireSmartLinkAdapter``: API de Linkfire (Q3 2025, paid).
- Self-hosted fallback: redirector propio en ``link.<dominio>/{short_id}``
  con tabla de redirects + log de clicks.

El value object ``SmartLink`` vive en domain/meta. El puerto solo orquesta
creacion + lookup + tracking de eventos.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from streaming_bot.domain.exceptions import TransientError
from streaming_bot.domain.meta.smart_link import SmartLink
from streaming_bot.domain.value_objects import Country


class SmartLinkProviderError(TransientError):
    """Error reintentable del provider (5xx, timeout, rate limit)."""


@dataclass(frozen=True, slots=True)
class ClickEvent:
    """Evento de click registrado por el provider.

    El spillover orchestrator agrega estos eventos por (track, pais) para
    correlacionar con el uplift en Spotify for Artists.
    """

    short_id: str
    country: Country | None  # None si geoip fallo
    dsp_target: str | None
    user_agent: str | None
    occurred_at: datetime


@runtime_checkable
class ISmartLinkProvider(Protocol):
    """Crea, recupera y trackea smart links."""

    async def create_link(
        self,
        *,
        track_uri: str,
        target_dsps: dict[Country, dict[str, str]],
        slug_hint: str | None = None,
    ) -> SmartLink:
        """Crea un nuevo smart-link.

        ``slug_hint`` es opcional: si el provider lo soporta, el ``short_id``
        usara el slug; si no, el provider genera uno aleatorio.
        """
        ...

    async def get_link(self, *, short_id: str) -> SmartLink | None:
        """Recupera un smart-link previamente creado, o None."""
        ...

    async def track_click(self, event: ClickEvent) -> None:
        """Registra un click. En el fallback self-hosted lo escribe a un
        log estructurado; en Linkfire es no-op (Linkfire trackea solo).
        """
        ...
