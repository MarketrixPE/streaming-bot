"""Playlist como recurso de propagacion de streams (estrategia playlist-first).

Tres capas:
1. PROJECT_PLAYLIST: 50-100 playlists publicas curadas con mezcla target+camuflaje.
2. PERSONAL_PLAYLIST: ~30 playlists privadas por cuenta (cada cuenta arma las suyas).
3. CAMOUFLAGE_POOL: ~5000 canciones reales populares por genero/territorio.

El bot reproduce playlists (no canciones aisladas), aprovechando el auto-advance
para encadenar streams en una sola sesion. Esto humaniza el comportamiento
y hace el patron 10x mas dificil de detectar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from streaming_bot.domain.value_objects import Country


class PlaylistKind(str, Enum):
    """Capa a la que pertenece la playlist."""

    PROJECT_PUBLIC = "project_public"  # publica, contiene targets
    PERSONAL_PRIVATE = "personal_private"  # privada de cada cuenta
    CAMOUFLAGE_GENRE = "camouflage_genre"  # cancha real por genero, sin targets
    EDITORIAL_REPLICA = "editorial_replica"  # replica de top oficial Spotify


class PlaylistVisibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    UNLISTED = "unlisted"


@dataclass(frozen=True, slots=True)
class PlaylistTrack:
    """Pista dentro de una playlist con su rol estrategico."""

    track_uri: str  # spotify:track:abc123
    position: int  # 0-indexed
    is_target: bool  # True si es cancion del catalogo Tony Jaxx
    duration_ms: int = 0
    artist_uri: str = ""
    title: str = ""

    def __post_init__(self) -> None:
        if self.position < 0:
            raise ValueError(f"position negativa: {self.position}")


@dataclass(slots=True)
class Playlist:
    """Playlist en el ecosistema del bot."""

    id: str
    spotify_id: str | None
    name: str
    kind: PlaylistKind
    visibility: PlaylistVisibility
    owner_account_id: str | None
    territory: Country | None  # publico objetivo geo
    genre: str | None  # "reggaeton", "trap_latino", "perreo"
    tracks: list[PlaylistTrack] = field(default_factory=list)
    description: str = ""
    cover_image_path: str | None = None
    follower_count: int = 0
    last_synced_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def new(
        cls,
        *,
        name: str,
        kind: PlaylistKind,
        visibility: PlaylistVisibility = PlaylistVisibility.PRIVATE,
        owner_account_id: str | None = None,
        territory: Country | None = None,
        genre: str | None = None,
    ) -> Playlist:
        return cls(
            id=str(uuid4()),
            spotify_id=None,
            name=name,
            kind=kind,
            visibility=visibility,
            owner_account_id=owner_account_id,
            territory=territory,
            genre=genre,
        )

    @property
    def total_tracks(self) -> int:
        return len(self.tracks)

    @property
    def target_tracks(self) -> list[PlaylistTrack]:
        return [t for t in self.tracks if t.is_target]

    @property
    def target_ratio(self) -> float:
        if not self.tracks:
            return 0.0
        return len(self.target_tracks) / len(self.tracks)

    @property
    def estimated_duration_minutes(self) -> int:
        return sum(t.duration_ms for t in self.tracks) // 60_000

    def add_track(self, track: PlaylistTrack) -> None:
        if any(t.track_uri == track.track_uri for t in self.tracks):
            raise ValueError(f"track duplicada: {track.track_uri}")
        self.tracks.append(track)

    def link_to_spotify(self, spotify_id: str) -> None:
        self.spotify_id = spotify_id
        self.last_synced_at = datetime.now(UTC)
