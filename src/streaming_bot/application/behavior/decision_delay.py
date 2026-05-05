"""Politicas pluggables de delay de decision humana.

Cada vez que la engine va a tomar una decision (clicar, leer, hacer hover,
scrollear) introduce un delay realista *antes* de ejecutar. Esto evita que
las acciones se sucedan a velocidad sub-humana y rompan los detectores de
fingerprint conductual (Spotify, Beatdapp).

Diseno:
- `DecisionDelayPolicy`: protocolo principal. Recibe el tipo de decision y
  metadatos de la persona/contexto y devuelve un delay en ms (>=0).
- Implementaciones provistas:
  - `LogNormalDelayPolicy` (default): distribucion log-normal por tipo de
    decision; modulada por engagement_level y hora local.
  - `NullDelayPolicy`: para tests / sesiones sin delays.
  - `OpenAIDelayPolicy`: opcional, gateado por env (`OPENAI_API_KEY`).
    Cuando esta presente delega a un LLM la decision del delay; si el LLM
    falla cae a `LogNormalDelayPolicy` para no bloquear la sesion.

La engine puede mezclar politicas (compose) sin acoplarse a ninguna concreta.
"""

from __future__ import annotations

import math
import os
import random
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from streaming_bot.domain.persona import EngagementLevel


class DecisionType(str, Enum):
    """Categoria de la decision que requiere delay.

    El catalogo es deliberadamente corto: cada tipo agrupa decisiones humanas
    de coste cognitivo similar. Si en el futuro un tipo nuevo tiene
    caracteristicas distintas, anadirlo con su mu/sigma calibrado.
    """

    CLICK = "click"
    READ = "read"
    HOVER = "hover"
    SCROLL = "scroll"
    NAVIGATE = "navigate"
    TYPE = "type"


@dataclass(frozen=True, slots=True)
class DelayContext:
    """Contexto que la politica usa para modular el delay base.

    `engagement_level` se pasa como string para que la politica no tenga que
    importar `domain.persona` (mantenemos limites de modulo limpios).
    `local_hour` es 0..23 segun el timezone de la persona.
    """

    decision: DecisionType
    engagement_level: str | None = None
    local_hour: int | None = None
    label: str | None = None


class DecisionDelayPolicy(Protocol):
    """Politica que produce un delay en milisegundos para una decision."""

    async def decide(self, context: DelayContext) -> int:
        """Devuelve un delay >= 0 en milisegundos."""
        ...


# ── NullDelayPolicy ──────────────────────────────────────────────────────


class NullDelayPolicy:
    """Politica trivial: 0ms siempre. Util en tests y benchmarks."""

    async def decide(self, context: DelayContext) -> int:
        _ = context
        return 0


# ── LogNormalDelayPolicy ─────────────────────────────────────────────────

# Calibracion empirica: cada tipo tiene `mu` y `sigma` en log-segundos.
# Producen delays con distribucion log-normal cuyo modo aproximado va de
# ~0.1s (hover) a ~2.5s (read). Los valores estan basados en mediciones
# medias de UX research sobre interacciones web.
_LOG_NORMAL_PARAMS: dict[DecisionType, tuple[float, float]] = {
    DecisionType.CLICK: (math.log(0.45), 0.55),
    DecisionType.READ: (math.log(2.0), 0.65),
    DecisionType.HOVER: (math.log(0.18), 0.50),
    DecisionType.SCROLL: (math.log(0.30), 0.55),
    DecisionType.NAVIGATE: (math.log(0.90), 0.50),
    DecisionType.TYPE: (math.log(0.22), 0.40),
}

# Modificadores por engagement: usuarios fanaticos deciden mas rapido (familiares
# con la UI), lurkers titubean mas. Multiplicador sobre el delay sampleado.
_ENGAGEMENT_FACTORS: Mapping[str, float] = {
    "fanatic": 0.8,
    "engaged": 0.95,
    "casual": 1.0,
    "lurker": 1.25,
}


class LogNormalDelayPolicy:
    """Politica log-normal por tipo de decision.

    Implementa la distribucion clasica usada en investigaciones de
    interaccion humano-computador (Sears & Jacko, 2007). Los parametros
    base se modulan por:
    - `engagement_level`: factor multiplicativo (`_ENGAGEMENT_FACTORS`).
    - `local_hour`: durante la madrugada (00-06) y la noche tardia (22-23)
      el usuario es mas lento (factor 1.15-1.30).
    """

    def __init__(self, *, rng_seed: int | None = None, hard_cap_ms: int = 30_000) -> None:
        self._rng = random.Random(rng_seed) if rng_seed is not None else random.Random()  # noqa: S311
        self._hard_cap_ms = hard_cap_ms

    async def decide(self, context: DelayContext) -> int:
        mu, sigma = _LOG_NORMAL_PARAMS.get(
            context.decision,
            _LOG_NORMAL_PARAMS[DecisionType.CLICK],
        )
        seconds = math.exp(self._rng.gauss(mu, sigma))
        seconds *= _engagement_factor(context.engagement_level)
        seconds *= _hour_factor(context.local_hour)
        ms = int(seconds * 1000.0)
        return max(0, min(ms, self._hard_cap_ms))


def _engagement_factor(level: str | None) -> float:
    """Multiplicador por engagement_level (case-insensitive)."""
    if not level:
        return 1.0
    return _ENGAGEMENT_FACTORS.get(level.lower(), 1.0)


def _hour_factor(hour: int | None) -> float:
    """Multiplicador por hora local: noche/madrugada penaliza la velocidad."""
    if hour is None:
        return 1.0
    hour_norm = hour % 24
    if 0 <= hour_norm < 6:
        return 1.30
    if hour_norm >= 22:
        return 1.15
    if 9 <= hour_norm < 12:
        return 0.95
    return 1.0


# ── OpenAIDelayPolicy (opcional, gateado por env) ────────────────────────


class OpenAIDelayPolicy:
    """Politica que delega la decision del delay a un LLM.

    Diseno defensivo:
    - Se instancia solo si `OPENAI_API_KEY` esta presente (chequeado por el
      builder, no por esta clase, para que sea testable con mocks).
    - Si la llamada al LLM falla o devuelve algo invalido, cae a la
      politica `fallback` (por defecto `LogNormalDelayPolicy`). No queremos
      que una sesion se cuelgue por un timeout de OpenAI.
    - El cliente se inyecta como callable async `(prompt) -> str` para no
      depender directamente de `httpx` ni del SDK de OpenAI; la integracion
      vive en infrastructure.
    """

    def __init__(
        self,
        *,
        fallback: DecisionDelayPolicy,
        llm_callable: _LlmCallable,
        cap_ms: int = 30_000,
    ) -> None:
        self._fallback = fallback
        self._llm = llm_callable
        self._cap_ms = cap_ms

    async def decide(self, context: DelayContext) -> int:
        prompt = (
            f"Eres un modelo de comportamiento humano. Devuelve UN entero (ms) "
            f"para el delay antes de una decision tipo '{context.decision.value}' "
            f"para un usuario engagement={context.engagement_level} a las "
            f"{context.local_hour}:00 hora local. Solo el numero, sin texto."
        )
        try:
            raw = await self._llm(prompt)
        except Exception:
            # Falla blanda: nunca rompemos la sesion por el LLM.
            return await self._fallback.decide(context)
        try:
            ms = int(str(raw).strip())
        except ValueError:
            return await self._fallback.decide(context)
        return max(0, min(ms, self._cap_ms))


# Tipo del callable async que la OpenAIDelayPolicy espera.
class _LlmCallable(Protocol):
    async def __call__(self, prompt: str) -> str: ...


# ── Builder ──────────────────────────────────────────────────────────────


def build_default_delay_policy(
    *,
    engagement: EngagementLevel | None = None,
    rng_seed: int | None = None,
    llm_callable: _LlmCallable | None = None,
    env: Mapping[str, str] | None = None,
) -> DecisionDelayPolicy:
    """Devuelve la politica por defecto segun el entorno.

    Reglas:
    - Si `OPENAI_API_KEY` esta presente y `llm_callable` se pasa, se usa
      `OpenAIDelayPolicy` con fallback log-normal.
    - En cualquier otro caso, se usa `LogNormalDelayPolicy` puro.

    `engagement` se acepta para que el caller no tenga que mantener el string
    a mano; la politica solo necesita el `.value`.
    """
    env = env if env is not None else os.environ
    base = LogNormalDelayPolicy(rng_seed=rng_seed)
    has_key = bool(env.get("OPENAI_API_KEY", "").strip())
    if has_key and llm_callable is not None:
        return OpenAIDelayPolicy(fallback=base, llm_callable=llm_callable)
    _ = engagement
    return base


def now_local_hour(now: datetime, timezone_offset_hours: int = 0) -> int:
    """Calcula la hora local 0..23 dado un `datetime` y un offset.

    Ayuda al caller a no acoplarse a `zoneinfo` cuando solo necesita la hora.
    """
    return (now.hour + timezone_offset_hours) % 24
