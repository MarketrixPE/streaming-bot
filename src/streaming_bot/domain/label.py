"""Sello discografico / cuenta de distribuidor.

Un Label representa una entidad legal o comercial que distribuye musica
a Spotify (DistroKid, OneRPM, aiCom). Multiples artistas pueden compartir
un Label (ej. Worldwide Hits aglutina varios proyectos).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4


class DistributorType(str, Enum):
    """Distribuidores soportados."""

    DISTROKID = "distrokid"
    ONERPM = "onerpm"
    AICOM = "aicom"
    SPOTIFY_FOR_ARTISTS = "spotify_for_artists"
    UNITED_MASTERS = "united_masters"
    AMUSE = "amuse"
    OTHER = "other"


class LabelHealth(str, Enum):
    """Estado de salud del label en el distribuidor."""

    HEALTHY = "healthy"
    WARNING = "warning"  # warning recibido (no bloqueante)
    PAYMENT_HOLD = "payment_hold"  # pagos retenidos
    SUSPENDED = "suspended"  # cuenta suspendida


@dataclass(slots=True)
class Label:
    """Sello/cuenta de distribuidor.

    Para fines del bot, esta entidad NO controla cuentas listening:
    eso lo hace el pool de Account (cuentas de spotify cliente).
    Aqui modelamos la cuenta donde se monitorea el resultado del boost.
    """

    id: str
    name: str
    distributor: DistributorType
    distributor_account_id: str | None = None  # ID interno en el distribuidor
    owner_email: str | None = None
    health: LabelHealth = LabelHealth.HEALTHY
    last_health_check: datetime | None = None
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def new(
        cls,
        *,
        name: str,
        distributor: DistributorType,
        distributor_account_id: str | None = None,
        owner_email: str | None = None,
    ) -> Label:
        return cls(
            id=str(uuid4()),
            name=name,
            distributor=distributor,
            distributor_account_id=distributor_account_id,
            owner_email=owner_email,
        )

    def update_health(self, health: LabelHealth, note: str = "") -> None:
        self.health = health
        self.last_health_check = datetime.now(UTC)
        if note:
            self.notes = note
        self.updated_at = datetime.now(UTC)

    @property
    def is_safe_to_operate(self) -> bool:
        """True si se pueden seguir generando streams para artistas de este label."""
        return self.health in {LabelHealth.HEALTHY, LabelHealth.WARNING}
