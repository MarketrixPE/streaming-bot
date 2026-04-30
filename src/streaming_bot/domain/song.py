"""Catálogo de canciones objetivo y canciones de camuflaje."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from streaming_bot.domain.value_objects import Country


class Distributor(str, Enum):
    """De dónde se distribuye la canción."""

    DISTROKID = "distrokid"
    ONERPM = "onerpm"
    CDBABY = "cdbaby"
    TUNECORE = "tunecore"
    UNITED_MASTERS = "united_masters"
    OTHER = "other"


class SongRole(str, Enum):
    """Rol de la canción en el catálogo del bot."""

    TARGET = "target"  # canción tuya, objetivo del lift
    CAMOUFLAGE = "camouflage"  # canción ajena, usada como cover
    DISCOVERY = "discovery"  # canción usada en sesiones de Discover Weekly


class SongTier(str, Enum):
    """Tier de salud orgánica de la canción.

    Decide la política de boosting:
    - HOT/RISING: protegidos, NO boostear (pueden perder algoritmo orgánico).
    - MID/LOW: candidatos a boost moderado.
    - ZOMBIE: cero streams en Spotify pero potencial; objetivo prioritario.
    - DEAD: descartados (sin tracción ni potencial).
    - FLAGGED: detectados con spike anómalo histórico (ej. Oct'25), excluidos
      del piloto y bajo monitoreo extra.
    """

    HOT = "hot"
    RISING = "rising"
    MID = "mid"
    LOW = "low"
    ZOMBIE = "zombie"
    DEAD = "dead"
    FLAGGED = "flagged"


@dataclass(frozen=True, slots=True)
class SongMetadata:
    """Metadata enriquecida desde Spotify for Artists o ingest manual."""

    duration_seconds: int
    explicit: bool = False
    release_date: date | None = None
    isrc: str | None = None
    album_uri: str | None = None
    label: str | None = None
    genres: tuple[str, ...] = field(default_factory=tuple)
    primary_market: Country | None = None


@dataclass(slots=True)
class Song:
    """Canción del catálogo o de camuflaje.

    Para canciones TARGET, `baseline_streams_per_day` y `target_streams_per_day`
    son lo que el scheduler usará para distribuir el trabajo.

    Multi-artist: cada canción tiene un `primary_artist_id` (FK a Artist) y
    opcionalmente `featured_artist_ids`. Los nombres de artista se mantienen
    como cache denormalizado para no hacer joins innecesarios en hot paths.
    """

    spotify_uri: str  # spotify:track:XXXX
    title: str
    artist_name: str  # cache denormalizado (artista principal)
    artist_uri: str  # spotify:artist:XXXX (artista principal)
    role: SongRole
    metadata: SongMetadata

    # Multi-artist: FKs al dominio Artist + Label
    primary_artist_id: str | None = None  # FK a Artist (id ULID/UUID)
    featured_artist_ids: tuple[str, ...] = ()  # FKs adicionales (features)
    label_id: str | None = None  # FK a Label

    distributor: Distributor | None = None

    # Solo para TARGET songs
    baseline_streams_per_day: float = 0.0  # promedio rolling 7-day orgánico
    target_streams_per_day: int = 0  # objetivo a alcanzar al final del ramp-up
    current_streams_today: int = 0  # tracking en runtime
    is_active: bool = True  # kill-switch por canción
    tier: SongTier = SongTier.MID

    # Forensia anti-detección
    spike_oct2025_flag: bool = False  # canción que recibió boost en Oct'25
    flag_notes: str = ""  # razón del flag (ej. "spike 8x oct vs sep+nov")

    # Demografía (top 5 países desde Spotify for Artists)
    top_country_distribution: dict[Country, float] = field(default_factory=dict)

    @property
    def is_target(self) -> bool:
        return self.role == SongRole.TARGET

    @property
    def is_pilot_eligible(self) -> bool:
        """Solo zombies/low/mid no flagged son aptas para piloto."""
        if self.spike_oct2025_flag:
            return False
        return (
            self.role == SongRole.TARGET
            and self.is_active
            and self.tier in {SongTier.ZOMBIE, SongTier.LOW, SongTier.MID}
        )

    def safe_ceiling_today(self) -> int:
        """Tope diario seguro: no más de +50% sobre baseline 7-day rolling.

        Beatdapp detecta spikes >50% sostenidos sobre baseline.
        """
        if self.baseline_streams_per_day < 1:
            return max(int(self.target_streams_per_day * 0.20), 5)
        return min(
            int(self.baseline_streams_per_day * 1.5),
            self.target_streams_per_day,
        )

    def remaining_capacity_today(self) -> int:
        """Cuántos streams adicionales puede recibir hoy."""
        ceiling = self.safe_ceiling_today()
        return max(ceiling - self.current_streams_today, 0)
