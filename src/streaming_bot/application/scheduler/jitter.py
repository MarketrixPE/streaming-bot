"""Utilidades puras de jitter para evitar patrones detectables.

Filosofia:
- Funciones puras sin estado global.
- Aceptan ``random.Random`` inyectado para tests deterministicos.
- Inputs/outputs estrictos; raises ``ValueError`` ante parametros invalidos.

Las funciones se usan tanto desde ``DailyPlanner`` (jitter de volumen)
como desde ``TimeOfDayDistributor`` (jitter temporal por job) y desde
``SchedulerService`` (decision de "rest day" por cancion/cuenta).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta


def apply_target_jitter(
    target: int,
    pct: float = 0.15,
    *,
    rng: random.Random | None = None,
) -> int:
    """Aplica un jitter porcentual simetrico al volumen objetivo.

    Args:
        target: numero de streams base (>= 0).
        pct: amplitud del jitter (0.15 -> ±15%). Debe ser >= 0.
        rng: ``random.Random`` opcional para reproducibilidad.

    Returns:
        Nuevo target redondeado, nunca negativo.
    """
    if target < 0:
        raise ValueError(f"target negativo: {target}")
    if pct < 0:
        raise ValueError(f"pct negativo: {pct}")
    if target == 0 or pct == 0:
        return target
    r = rng if rng is not None else random.Random()  # noqa: S311
    factor = 1.0 + r.uniform(-pct, pct)
    return max(0, round(target * factor))


def apply_time_jitter(
    scheduled: datetime,
    max_minutes: int = 12,
    *,
    rng: random.Random | None = None,
) -> datetime:
    """Desplaza un instante por un jitter simetrico en minutos.

    Args:
        scheduled: instante base.
        max_minutes: amplitud del jitter (12 -> ±12 minutos). Debe ser >= 0.
        rng: ``random.Random`` opcional para reproducibilidad.

    Returns:
        ``datetime`` desplazado dentro del rango ``[-max, +max]`` minutos.
    """
    if max_minutes < 0:
        raise ValueError(f"max_minutes negativo: {max_minutes}")
    if max_minutes == 0:
        return scheduled
    r = rng if rng is not None else random.Random()  # noqa: S311
    delta_minutes = r.uniform(-float(max_minutes), float(max_minutes))
    return scheduled + timedelta(minutes=delta_minutes)


def should_skip_today(
    rng: random.Random,
    skip_chance: float = 0.05,
) -> bool:
    """Decide aleatoriamente si la unidad descansa hoy (anti-patron).

    Util para que cuentas/canciones tengan dias en blanco esporadicos
    que rompan la regularidad detectable.

    Args:
        rng: generador random aislado (obligatorio).
        skip_chance: probabilidad de saltar hoy (0.05 -> 5%).

    Returns:
        True si toca descansar.
    """
    if not 0.0 <= skip_chance <= 1.0:
        raise ValueError(f"skip_chance fuera de rango: {skip_chance}")
    return rng.random() < skip_chance
