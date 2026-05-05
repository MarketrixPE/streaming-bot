"""Snapshot agregado del comportamiento de escucha de una cuenta Deezer.

El historial es la fuente de verdad para evaluar si una cuenta cumple
`SuperFanProfile`. Toda la informacion se mide sobre los ultimos 30 dias
para alinear con la ventana que Deezer usa internamente para calcular
ACPS.

Este value object es **inmutable** (frozen + slots). No hace I/O; las
implementaciones de `IDeezerClient` lo construyen a partir de la respuesta
de la API privada (`/ajax/gw-light.php`) y lo devuelven al dominio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from streaming_bot.domain.deezer.super_fan_profile import SuperFanProfile


@dataclass(frozen=True, slots=True)
class ProfileGap:
    """Diferencias entre la cuenta actual y `SuperFanProfile`.

    Sirve para que `SuperFanEligibilityService` y `DeezerRoutingPolicy`
    razonen sobre "cuanto le falta" a una cuenta para ser super-fan, y
    asignen tracks de manera incremental al pipeline de construccion.
    """

    artists_followed_missing: int
    avg_session_minutes_missing: float
    replay_rate_missing: float
    distinct_tracks_30d_missing: int
    distinct_albums_30d_missing: int

    @property
    def is_zero(self) -> bool:
        """True si la cuenta cumple todos los umbrales del perfil."""
        return (
            self.artists_followed_missing <= 0
            and self.avg_session_minutes_missing <= 0
            and self.replay_rate_missing <= 0
            and self.distinct_tracks_30d_missing <= 0
            and self.distinct_albums_30d_missing <= 0
        )


@dataclass(frozen=True, slots=True)
class DeezerListenerHistory:
    """Snapshot inmutable del comportamiento de la cuenta en 30 dias.

    Atributos:
    - `account_id`: identificador interno de la cuenta dentro del bot.
    - `artists_followed`: tupla de IDs de artista seguidos.
    - `avg_session_minutes_30d`: media de duracion de sesion (minutos).
    - `replay_rate`: ratio replays/plays_unicos en [0, 1].
    - `distinct_tracks_30d`: tracks unicos escuchados en 30 dias.
    - `distinct_albums_30d`: albumes unicos escuchados en 30 dias.
    - `last_session_at`: ultima sesion detectada; None si nunca activa.
    """

    account_id: str
    artists_followed: tuple[str, ...] = field(default_factory=tuple)
    avg_session_minutes_30d: float = 0.0
    replay_rate: float = 0.0
    distinct_tracks_30d: int = 0
    distinct_albums_30d: int = 0
    last_session_at: datetime | None = None

    def __post_init__(self) -> None:
        # Validar invariantes: ratios fuera de [0, 1] o conteos negativos
        # son siempre datos corruptos: explotamos en construccion.
        if not 0.0 <= self.replay_rate <= 1.0:
            raise ValueError(f"replay_rate fuera de [0, 1]: {self.replay_rate}")
        if self.avg_session_minutes_30d < 0:
            raise ValueError(
                f"avg_session_minutes_30d debe ser >= 0: {self.avg_session_minutes_30d}"
            )
        if self.distinct_tracks_30d < 0:
            raise ValueError(
                f"distinct_tracks_30d debe ser >= 0: {self.distinct_tracks_30d}"
            )
        if self.distinct_albums_30d < 0:
            raise ValueError(
                f"distinct_albums_30d debe ser >= 0: {self.distinct_albums_30d}"
            )

    @property
    def artists_followed_count(self) -> int:
        """Cantidad de artistas seguidos. Atajo para no recalcular len()."""
        return len(self.artists_followed)

    def gap_against(self, profile: SuperFanProfile) -> ProfileGap:
        """Calcula cuanto le falta a la cuenta para cumplir cada umbral.

        Un valor `<= 0` en algun campo significa "cumple ese umbral". El
        signo se preserva intencionalmente: `RoutingPolicy` puede usarlo
        para priorizar cuentas que ya estan cerca del perfil pleno.
        """
        return ProfileGap(
            artists_followed_missing=profile.artists_followed_min
            - self.artists_followed_count,
            avg_session_minutes_missing=profile.avg_session_minutes_min
            - self.avg_session_minutes_30d,
            replay_rate_missing=profile.replay_rate_min - self.replay_rate,
            distinct_tracks_30d_missing=profile.distinct_tracks_30d_min
            - self.distinct_tracks_30d,
            distinct_albums_30d_missing=profile.distinct_albums_30d_min
            - self.distinct_albums_30d,
        )

    def matches(self, profile: SuperFanProfile) -> bool:
        """True si la cuenta cumple TODOS los umbrales de `profile`."""
        return self.gap_against(profile).is_zero
