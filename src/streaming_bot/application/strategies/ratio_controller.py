"""Controlador central de ratios humanos save/skip/queue/like.

El `RatioController` es la pieza que evita la red flag mas obvia para
Beatdapp: que TODAS las cuentas guarden el target track. La sola tasa
agregada de saves disparada hacia 1.0 (frente al ~4% organico) es
suficiente para tipificar el patron como artificial.

Diseno:
- Pure (no I/O): toma el historial de acciones recientes en la sesion y
  decide la siguiente intent. El caller (strategy v2 o use case) es quien
  persiste el historial y registra los efectos.
- Stateless por defecto: el caller pasa `recent_history`. La engine lo
  consume para reconstruir la EMA en cada llamada. Si el caller quiere
  performance opcional, puede mantener el estado externo y pasar slices.
- Smoothing exponencial (EMA): asigna mas peso a las acciones recientes
  que a las del comienzo de la sesion, alineado con como humanos
  cambian de "mood" durante una escucha (Lavin et al. 2024, "Listener
  fatigue patterns").
- Sensibilidad ajustable: `sensitivity` define cuanto se desvia la
  probabilidad cuando la observacion se aleja del target.

Algoritmo (resumen):
1. Calcular EMA de cada intent sobre `recent_history`.
2. Resolver `RatioTargets` efectivos para la persona (geo + genero).
3. Para cada intent (save, skip, queue, like) en orden aleatorio:
   - p = target * (1 + clamp((target - observed) / target, -1, 1) * sensitivity)
   - Si rng.random() < p, retornar esa intent.
4. Si ninguna intent cae, retornar BehaviorIntent.NONE.

El orden aleatorio entre intents evita que la primera dispare siempre
y "consuma" la decision; con shuffle, cada intent tiene chance justa
proporcional a su probabilidad ajustada.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from streaming_bot.application.strategies.ratio_targets import RatioTargets

if TYPE_CHECKING:
    from streaming_bot.domain.persona import Persona


class BehaviorIntent(str, Enum):
    """Intencion siguiente decidida por el `RatioController`.

    Conjunto deliberadamente acotado a las 4 acciones que mueven los
    detectores de Beatdapp; el resto de behaviors (visit_artist, scroll,
    pause, etc.) los gobierna el `HumanBehaviorEngine` con sus propias
    probabilidades por persona.
    """

    SAVE_TRACK = "save_track"
    SKIP_TRACK = "skip_track"
    ADD_TO_QUEUE = "add_to_queue"
    LIKE_ARTIST = "like_artist"
    NONE = "none"


# Mapeo intent -> nombre del campo en RatioTargets. Lo mantenemos como tabla
# para no acoplar el enum a los nombres de campos (cambiar uno no rompe el
# otro).
_INTENT_TO_FIELD: dict[BehaviorIntent, str] = {
    BehaviorIntent.SAVE_TRACK: "save_rate",
    BehaviorIntent.SKIP_TRACK: "skip_rate",
    BehaviorIntent.ADD_TO_QUEUE: "queue_rate",
    BehaviorIntent.LIKE_ARTIST: "like_rate",
}


# Default razonable: priorizamos las acciones recientes con peso ~0.30
# (despues de ~10 muestras la EMA esta estabilizada al 95%).
_DEFAULT_SMOOTHING_ALPHA = 0.30
# Sensibilidad: cuanto sube/baja la prob ajustada respecto al target en el
# extremo de la desviacion. 0.6 = +-60% sobre el target.
_DEFAULT_SENSITIVITY = 0.60
# Cuando la observacion se aleja muchisimo del target la formula podria dar
# valores fuera de [0, 1]; siempre clampeamos al final.
_MAX_PROBABILITY = 1.0


@dataclass(frozen=True, slots=True)
class RatioControllerConfig:
    """Configuracion estatica del controlador.

    `smoothing_alpha`: peso EMA de la accion mas reciente (0..1). Valores
    altos reaccionan rapido pero aumentan la varianza; valores bajos
    suavizan mucho y tardan en converger.

    `sensitivity`: cuanto se separa la probabilidad efectiva del target
    cuando la observacion esta saturada (delta = +-1).
    """

    smoothing_alpha: float = _DEFAULT_SMOOTHING_ALPHA
    sensitivity: float = _DEFAULT_SENSITIVITY

    def __post_init__(self) -> None:
        if not 0.0 < self.smoothing_alpha <= 1.0:
            raise ValueError(
                f"smoothing_alpha={self.smoothing_alpha} debe estar en (0, 1]",
            )
        if not 0.0 <= self.sensitivity <= 1.0:
            raise ValueError(
                f"sensitivity={self.sensitivity} debe estar en [0, 1]",
            )


class RatioController:
    """Decide la proxima intent (save/skip/queue/like) en funcion de la
    persona y del historial reciente de acciones.

    No mantiene estado mutable salvo el RNG. El historial vive en el
    caller, que es libre de persistirlo en el `SessionRecord` o en el
    `PersonaMemoryDelta`.
    """

    def __init__(
        self,
        *,
        targets: RatioTargets | None = None,
        config: RatioControllerConfig | None = None,
        rng_seed: int | None = None,
    ) -> None:
        # Si el caller no pasa targets, asumimos defaults globales 2026.
        # En tiempo de uso real, el SpotifyV2 strategy pide
        # `RatioTargets.for_persona(persona)` y los inyecta aqui.
        self._fallback_targets = targets or RatioTargets.default()
        self._config = config or RatioControllerConfig()
        # RNG aislado: mismo seed -> misma secuencia de decisiones.
        # No es seguridad criptografica, es jitter de comportamiento.
        self._rng = random.Random(rng_seed) if rng_seed is not None else random.Random()  # noqa: S311

    @property
    def config(self) -> RatioControllerConfig:
        return self._config

    @property
    def fallback_targets(self) -> RatioTargets:
        return self._fallback_targets

    # ── API publica ───────────────────────────────────────────────────────
    def next_action(
        self,
        *,
        persona: Persona | None = None,
        recent_history: Sequence[BehaviorIntent] = (),
        targets: RatioTargets | None = None,
    ) -> BehaviorIntent:
        """Decide la siguiente intent dada la persona y el historial.

        Si `targets` se pasa explicitamente, se usa; si no, se calcula
        a partir de la persona via `RatioTargets.for_persona`. Si tampoco
        hay persona, se cae al `fallback_targets` del controlador.
        """
        effective_targets = self._resolve_targets(persona, targets)
        observed = self._compute_ema(recent_history)

        # Tiramos en orden aleatorio para que ninguna intent monopolice
        # la decision sistematicamente. Si una intent dispara, se ignoran
        # las restantes en este turno; eso refleja como un humano no hace
        # save+skip+queue al mismo tiempo en un track.
        intents = list(_INTENT_TO_FIELD.keys())
        self._rng.shuffle(intents)

        for intent in intents:
            target = float(getattr(effective_targets, _INTENT_TO_FIELD[intent]))
            observed_rate = observed.get(intent, 0.0)
            probability = self._adjust_probability(target=target, observed=observed_rate)
            if probability <= 0.0:
                continue
            if self._rng.random() < probability:
                return intent
        return BehaviorIntent.NONE

    def observed_rates(
        self,
        recent_history: Sequence[BehaviorIntent],
    ) -> dict[BehaviorIntent, float]:
        """Devuelve la EMA observada por intent. Util para tests y logs."""
        return self._compute_ema(recent_history)

    def adjusted_probability(
        self,
        *,
        target: float,
        observed: float,
    ) -> float:
        """Calcula la probabilidad ajustada para un target/observed dado.

        Util para inspeccion y para tests (verifica monotonia: si observed
        sube, la probabilidad baja).
        """
        return self._adjust_probability(target=target, observed=observed)

    # ── Helpers internos ──────────────────────────────────────────────────
    def _resolve_targets(
        self,
        persona: Persona | None,
        explicit: RatioTargets | None,
    ) -> RatioTargets:
        if explicit is not None:
            return explicit
        if persona is not None:
            return RatioTargets.for_persona(persona)
        return self._fallback_targets

    def _compute_ema(
        self,
        history: Sequence[BehaviorIntent],
    ) -> dict[BehaviorIntent, float]:
        """EMA por intent recorriendo `history` en orden cronologico.

        Para cada paso `entry`:
            ema[k] = alpha * (1 si entry == k else 0) + (1 - alpha) * ema[k]

        Inicializamos en 0.0; la EMA va subiendo a medida que la intent
        se observa con frecuencia.
        """
        alpha = self._config.smoothing_alpha
        ema: dict[BehaviorIntent, float] = dict.fromkeys(_INTENT_TO_FIELD, 0.0)
        if not history:
            return ema
        for entry in history:
            for kind, current in list(ema.items()):
                value = 1.0 if entry == kind else 0.0
                ema[kind] = alpha * value + (1.0 - alpha) * current
        return ema

    def _adjust_probability(self, *, target: float, observed: float) -> float:
        """Ajusta la probabilidad de ejecutar la intent en este turno.

        Formula:
            relative = clamp((target - observed) / target, -1, +1)
            p        = target * (1 + relative * sensitivity)

        Comportamiento esperado:
        - observed << target  -> p sube hasta target * (1 + sensitivity)
        - observed == target  -> p == target
        - observed >> target  -> p baja hasta target * (1 - sensitivity)

        Asi, las cuentas que ya saturaron la accion bajan la probabilidad
        de ejecutarla otra vez (alejando el patron del 100% siempre-save).
        """
        if target <= 0.0:
            return 0.0
        if observed >= 1.0:
            # Saturacion completa (improbable salvo en sesiones cortas).
            return 0.0
        denominator = max(target, 1e-6)
        relative = (target - observed) / denominator
        relative = max(-1.0, min(relative, 1.0))
        adjusted = target * (1.0 + relative * self._config.sensitivity)
        return max(0.0, min(adjusted, _MAX_PROBABILITY))
