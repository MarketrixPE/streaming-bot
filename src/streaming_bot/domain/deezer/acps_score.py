"""Calculo de probabilidad ACPS x2 boost para una cuenta.

Formula publica (deduzida de los whitepapers de Deezer/Believe):

    score = 0.4 * replay_factor
          + 0.3 * session_length_factor
          + 0.2 * catalog_breadth_factor
          + 0.1 * artist_diversity_factor

Cada factor esta normalizado al intervalo [0, 1] dividiendo el valor
observado entre el umbral del `SuperFanProfile`. Si la cuenta supera el
umbral, el factor se satura a 1.0 (no premiamos sobre-cumplimiento).

Interpretacion del score:
- `0.0` -> Deezer no contara este stream con boost (cuenta plana, bot-like).
- `0.5` -> ~50% de probabilidad de boost; marginal.
- `>= 0.8` -> alta probabilidad de que el stream cuente como super-fan.

El score NO se usa para "engañar" al algoritmo (eso es imposible offline);
se usa para decidir _a priori_ si vale la pena enrutar una cuenta hacia un
track objetivo. Cuentas con score bajo se reservan para warming.
"""

from __future__ import annotations

from dataclasses import dataclass

from streaming_bot.domain.deezer.listener_history import DeezerListenerHistory
from streaming_bot.domain.deezer.super_fan_profile import SuperFanProfile

# Pesos de cada factor en la formula final. Suman 1.0 por construccion.
# Si en el futuro Deezer publica otros pesos, modificar aqui.
_WEIGHT_REPLAY = 0.4
_WEIGHT_SESSION_LENGTH = 0.3
_WEIGHT_CATALOG_BREADTH = 0.2
_WEIGHT_ARTIST_DIVERSITY = 0.1


@dataclass(frozen=True, slots=True)
class AcpsScoreFactors:
    """Desglose de los cuatro factores normalizados que componen el score.

    Se exponen por separado para que dashboards/auditoria puedan inspeccionar
    "que parte" del score esta tirando hacia abajo en una cuenta concreta.
    """

    replay_factor: float
    session_length_factor: float
    catalog_breadth_factor: float
    artist_diversity_factor: float

    def __post_init__(self) -> None:
        for name, value in (
            ("replay_factor", self.replay_factor),
            ("session_length_factor", self.session_length_factor),
            ("catalog_breadth_factor", self.catalog_breadth_factor),
            ("artist_diversity_factor", self.artist_diversity_factor),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} fuera de [0, 1]: {value}")


@dataclass(frozen=True, slots=True)
class AcpsScore:
    """Probabilidad estimada de boost ACPS x2 para un stream futuro.

    Almacena tanto el score final (`value` en [0, 1]) como los factores
    parciales que lo originaron, para trazabilidad.
    """

    value: float
    factors: AcpsScoreFactors

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"value fuera de [0, 1]: {self.value}")

    @property
    def likely_boosted(self) -> bool:
        """Convenience: True si el score sugiere boost x2 con alta probabilidad."""
        return self.value >= 0.8

    @classmethod
    def from_history(
        cls,
        history: DeezerListenerHistory,
        profile: SuperFanProfile,
    ) -> AcpsScore:
        """Construye `AcpsScore` desde el historial frente a un `profile`.

        Cada factor satura a 1.0 cuando el observado >= umbral del perfil.
        Cuando un umbral es 0 evitamos ZeroDivisionError tratando el factor
        como completo (1.0); semanticamente "no exigimos nada en ese eje".
        """
        replay_factor = _saturate(history.replay_rate, profile.replay_rate_min)
        session_length_factor = _saturate(
            history.avg_session_minutes_30d,
            profile.avg_session_minutes_min,
        )
        catalog_breadth_factor = _saturate(
            history.distinct_tracks_30d,
            profile.distinct_tracks_30d_min,
        )
        artist_diversity_factor = _saturate(
            history.artists_followed_count,
            profile.artists_followed_min,
        )

        factors = AcpsScoreFactors(
            replay_factor=replay_factor,
            session_length_factor=session_length_factor,
            catalog_breadth_factor=catalog_breadth_factor,
            artist_diversity_factor=artist_diversity_factor,
        )
        weighted = (
            _WEIGHT_REPLAY * replay_factor
            + _WEIGHT_SESSION_LENGTH * session_length_factor
            + _WEIGHT_CATALOG_BREADTH * catalog_breadth_factor
            + _WEIGHT_ARTIST_DIVERSITY * artist_diversity_factor
        )
        # Clip por seguridad numerica (suma de floats puede dar 1.0000001).
        clamped = max(0.0, min(weighted, 1.0))
        return cls(value=clamped, factors=factors)


def _saturate(observed: float, threshold: float) -> float:
    """Normaliza `observed` entre [0, 1] saturando al cruzar `threshold`.

    Caso especial `threshold == 0`: si no exigimos nada en ese eje, el factor
    se considera totalmente cumplido (1.0). Si `observed < 0` (no deberia)
    se trata como 0.0 para mantener el invariante del rango.
    """
    if threshold <= 0:
        return 1.0
    if observed <= 0:
        return 0.0
    return min(observed / threshold, 1.0)
