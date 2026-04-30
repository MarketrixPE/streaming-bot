"""Puerto para monitorear distribuidores (DistroKid, OneRPM, Spotify for Artists).

El monitor verifica continuamente si hay alertas de "stream manipulation",
"filtered streams", warnings via email/dashboard, o caidas anomalas en pagos.

Si detecta cualquier signal de flag -> dispara `IPanicKillSwitch` que detiene
TODO el ramp-up inmediatamente.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable


class DistributorPlatform(str, Enum):
    DISTROKID = "distrokid"
    ONERPM = "onerpm"
    AICOM = "aicom"
    SPOTIFY_FOR_ARTISTS = "spotify_for_artists"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    FATAL = "fatal"  # cuenta cerrada, clawback confirmado


class AlertCategory(str, Enum):
    FILTERED_STREAMS = "filtered_streams"  # Spotify devolvio streams filtrados
    STREAM_MANIPULATION = "stream_manipulation"  # warning explicito
    PAYMENT_HOLD = "payment_hold"  # pagos retenidos
    ACCOUNT_REVIEW = "account_review"  # bajo review manual
    ACCOUNT_CLOSED = "account_closed"  # cerrada
    REVENUE_DROP = "revenue_drop"  # caida >40% mes-mes
    UNUSUAL_GEO_PATTERN = "unusual_geo_pattern"  # heuristica propia
    SUDDEN_STREAM_DROP = "sudden_stream_drop"  # heuristica propia
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DistributorAlert:
    """Alerta detectada en algun distribuidor."""

    platform: DistributorPlatform
    severity: AlertSeverity
    category: AlertCategory
    detected_at: datetime
    message: str
    affected_song_titles: tuple[str, ...] = ()
    raw_evidence: str = ""  # snapshot HTML/email/screenshot path

    @property
    def is_kill_switch_trigger(self) -> bool:
        """¿Esta alerta debe disparar el panic kill-switch?"""
        return self.severity in {AlertSeverity.CRITICAL, AlertSeverity.FATAL}


@runtime_checkable
class IDistributorMonitor(Protocol):
    """Monitor de un distribuidor especifico.

    Implementaciones: DistroKidMonitor, OneRPMMonitor, AiComMonitor,
    SpotifyForArtistsMonitor. Cada una scrapea su dashboard / lee emails.
    """

    @property
    def platform(self) -> DistributorPlatform: ...

    async def login_and_scrape(self) -> list[DistributorAlert]:
        """Login y scrape del dashboard. Devuelve alertas detectadas."""
        ...

    async def check_emails(self, since: datetime | None = None) -> list[DistributorAlert]:
        """Lee inbox del distribuidor en busca de warnings."""
        ...

    async def is_authenticated(self) -> bool:
        """¿La sesion sigue valida?"""
        ...


@runtime_checkable
class IPanicKillSwitch(Protocol):
    """Detiene TODO el ramp-up cuando un monitor detecta una alerta critica."""

    async def is_active(self) -> bool:
        """¿El kill-switch ya esta disparado?"""
        ...

    async def trigger(
        self,
        *,
        reason: str,
        triggering_alert: DistributorAlert | None = None,
    ) -> None:
        """Activa el kill-switch. Detiene el scheduler, cierra browsers, alerta ops."""
        ...

    async def reset(self, *, authorized_by: str, justification: str) -> None:
        """Desactiva manualmente. Solo para uso humano tras revision."""
        ...
