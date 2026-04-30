"""Artista como entidad de primer orden del catalogo.

Multi-artist support: cada cancion tiene un artista primario y opcionalmente
artistas featured. Cada artista tiene su pool aislado de cuentas, modems
y proxies para que la huella de uno no contamine a otro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from streaming_bot.domain.value_objects import Country


class ArtistRole(str, Enum):
    """Rol de un artista en una cancion."""

    PRIMARY = "primary"  # artista principal
    FEATURE = "feature"  # featuring (feat.)
    PRODUCER = "producer"  # productor
    REMIXER = "remixer"  # responsable de un remix


class ArtistStatus(str, Enum):
    """Estado operativo del artista en el programa."""

    ACTIVE = "active"
    PAUSED = "paused"  # cooling-off por flag detectado
    ARCHIVED = "archived"  # ya no se boostea


@dataclass(slots=True)
class Artist:
    """Artista cuyas canciones se boostean.

    Un artista tiene aislamiento operativo:
    - Pool propio de cuentas listening (no se mezclan entre artistas).
    - Politicas de ramp-up potencialmente distintas (artista nuevo vs establecido).
    - Monitoreo independiente en Spotify for Artists.
    """

    id: str
    name: str
    spotify_uri: str | None = None  # spotify:artist:XXXX
    aliases: tuple[str, ...] = ()
    primary_country: Country | None = None
    primary_genres: tuple[str, ...] = ()
    label_id: str | None = None  # FK opcional a Label
    status: ArtistStatus = ArtistStatus.ACTIVE
    has_spike_history: bool = False  # boost previo detectado
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def new(
        cls,
        *,
        name: str,
        spotify_uri: str | None = None,
        primary_country: Country | None = None,
        label_id: str | None = None,
    ) -> Artist:
        return cls(
            id=str(uuid4()),
            name=name,
            spotify_uri=spotify_uri,
            primary_country=primary_country,
            label_id=label_id,
        )

    def pause(self, reason: str) -> None:
        self.status = ArtistStatus.PAUSED
        self.notes = f"paused:{reason}"
        self.updated_at = datetime.now(UTC)

    def archive(self) -> None:
        self.status = ArtistStatus.ARCHIVED
        self.updated_at = datetime.now(UTC)

    def reactivate(self) -> None:
        self.status = ArtistStatus.ACTIVE
        self.notes = ""
        self.updated_at = datetime.now(UTC)

    def mark_with_spike_history(self, evidence: str) -> None:
        """Marca al artista como con historial de boost detectado.

        Este flag activa politica de cooling-off mas agresiva en el scheduler.
        """
        self.has_spike_history = True
        self.notes = f"spike_history:{evidence}"
        self.updated_at = datetime.now(UTC)
