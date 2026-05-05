"""Value-objects de dominio SoundCloud.

Todos los modelos son `frozen=True, slots=True` para impedir mutaciones
accidentales y mantenerlos hashables/comparables. No dependen de Flutter
ni de Playwright/httpx: el dominio no debe conocer detalles de transporte.

Modelos:
- `SoundcloudTrack`: metadata canonica de una pista (urn, perma, owner).
- `SoundcloudUser`: usuario/artista (followers, country opcional).
- `RepostChain`: cadena de reposts ordenada cronologicamente.
- `PremierEligibility`: snapshot de elegibilidad Premier para un track,
  con thresholds (1000 followers + 1000 monetizable plays/30d) y gap
  calculado para alimentar a `PremierBoostStrategy`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from streaming_bot.domain.value_objects import Country

# Constantes Premier Q1 2026: thresholds publicados por SoundCloud para
# elegibilidad del programa. Si SoundCloud actualiza la politica deberian
# moverse a un `PremierPolicy` configurable; por ahora hardcoded para
# evitar over-engineering en el primer drop.
DEFAULT_PREMIER_FOLLOWER_THRESHOLD = 1000
DEFAULT_PREMIER_PLAYS_THRESHOLD = 1000


@dataclass(frozen=True, slots=True)
class SoundcloudTrack:
    """Pista canonica de SoundCloud.

    `urn` es el identificador estable estilo `soundcloud:tracks:1234567`.
    `permalink_url` es la URL publica usada por la strategy Patchright para
    abrir el reproductor. `playback_count` puede llegar `None` si el
    endpoint privado lo oculta (rare, pero defensivo).
    """

    urn: str
    track_id: int
    title: str
    permalink_url: str
    duration_ms: int
    user_id: int
    playback_count: int | None = None
    likes_count: int | None = None
    reposts_count: int | None = None
    comment_count: int | None = None
    monetization_model: str | None = None  # "FREE" | "SUB_HIGH_TIER" | etc
    isrc: str | None = None


@dataclass(frozen=True, slots=True)
class SoundcloudUser:
    """Usuario/artista de SoundCloud.

    `country` es opcional porque SoundCloud no siempre lo expone (privacy).
    `followers_count` es la metrica que usa `PremierEligibilityService`
    para evaluar el threshold de 1000 followers.
    """

    user_id: int
    permalink: str  # slug, ej "djsnake"
    username: str
    followers_count: int
    country: Country | None = None
    verified: bool = False


@dataclass(frozen=True, slots=True)
class RepostChain:
    """Cadena de reposts de un track ordenada cronologicamente.

    Util para detectar burbujas de amplificacion (k-cluster) y para alimentar
    el grafo de seed accounts. El primer elemento es el reposter mas reciente.
    """

    track_urn: str
    reposter_user_ids: tuple[int, ...] = field(default_factory=tuple)

    @property
    def depth(self) -> int:
        return len(self.reposter_user_ids)


@dataclass(frozen=True, slots=True)
class PremierEligibility:
    """Snapshot de elegibilidad Premier para un track.

    Reglas de negocio:
    - `is_eligible` solo si followers >= threshold_followers Y
      monetizable_plays_30d >= threshold_plays.
    - `gap_followers` y `gap_monetizable_plays` se devuelven en positivo
      o cero (nunca negativo) para que el caller los pueda sumar al
      backlog de acciones.
    """

    track_urn: str
    followers: int
    monetizable_plays_30d: int
    threshold_followers: int = DEFAULT_PREMIER_FOLLOWER_THRESHOLD
    threshold_plays: int = DEFAULT_PREMIER_PLAYS_THRESHOLD

    def __post_init__(self) -> None:
        if self.followers < 0:
            raise ValueError(f"followers no puede ser negativo: {self.followers}")
        if self.monetizable_plays_30d < 0:
            raise ValueError(
                f"monetizable_plays_30d no puede ser negativo: {self.monetizable_plays_30d}",
            )
        if self.threshold_followers <= 0:
            raise ValueError("threshold_followers debe ser > 0")
        if self.threshold_plays <= 0:
            raise ValueError("threshold_plays debe ser > 0")

    @property
    def gap_followers(self) -> int:
        """Cuantos followers faltan para alcanzar el threshold (>=0)."""
        return max(0, self.threshold_followers - self.followers)

    @property
    def gap_monetizable_plays(self) -> int:
        """Cuantos plays monetizables faltan para alcanzar el threshold (>=0)."""
        return max(0, self.threshold_plays - self.monetizable_plays_30d)

    @property
    def is_eligible(self) -> bool:
        return self.gap_followers == 0 and self.gap_monetizable_plays == 0
