"""Generación de trayectorias Bezier para emular movimientos humanos del cursor.

Funciones puras (sin I/O ni dependencias de Playwright) que producen:
- Una curva Bezier de N puntos entre `start` y `end` con control points perturbados.
- Delays por punto con jitter gaussiano para emular variación de velocidad.
- Coordenadas de overshoot para simular un sobrepaso + corrección.

El RNG es inyectable para garantizar reproducibilidad determinista en tests.
"""

from __future__ import annotations

import math
from random import Random


def bezier_curve(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    control_points: int = 3,
    steps: int = 30,
    rng: Random | None = None,
    perturbation_factor: float = 0.15,
    min_perturbation_px: float = 20.0,
) -> list[tuple[float, float]]:
    """Devuelve `steps` puntos a lo largo de una curva Bezier de grado configurable.

    Genera `control_points` puntos de control intermedios perturbados
    perpendicularmente a la línea recta start→end. Luego usa el algoritmo
    de De Casteljau para muestrear la curva resultante.

    Args:
        start: punto de origen (x, y) del cursor.
        end: punto destino (x, y).
        control_points: cantidad de puntos de control intermedios (>=1).
        steps: número total de muestras a lo largo de la curva (>=2).
        rng: generador aleatorio reproducible. Si es None se usa uno nuevo.
        perturbation_factor: amplitud de la perturbación como fracción de la
            distancia start→end.
        min_perturbation_px: piso mínimo de perturbación (para distancias cortas).
    """
    if control_points < 1:
        raise ValueError("control_points debe ser >= 1")
    if steps < 2:
        raise ValueError("steps debe ser >= 2")

    rng = rng if rng is not None else Random()  # noqa: S311 (no es uso criptográfico)

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    distance = math.hypot(dx, dy)
    amplitude = max(min_perturbation_px, distance * perturbation_factor)

    # Vector perpendicular unitario para perturbar lateralmente cada control point.
    perp = (0.0, 0.0) if distance == 0.0 else (-dy / distance, dx / distance)

    points: list[tuple[float, float]] = [start]
    for i in range(1, control_points + 1):
        t = i / (control_points + 1)
        # Perturbación lateral + ruido axial menor para evitar simetría perfecta.
        lateral = rng.uniform(-amplitude, amplitude)
        axial = rng.uniform(-amplitude * 0.25, amplitude * 0.25)
        cx = start[0] + dx * t + perp[0] * lateral + (dx / max(distance, 1.0)) * axial
        cy = start[1] + dy * t + perp[1] * lateral + (dy / max(distance, 1.0)) * axial
        points.append((cx, cy))
    points.append(end)

    return [_de_casteljau(points, i / (steps - 1)) for i in range(steps)]


def _de_casteljau(points: list[tuple[float, float]], t: float) -> tuple[float, float]:
    """Evalúa una curva Bezier en parámetro t∈[0,1] vía De Casteljau."""
    pts = list(points)
    while len(pts) > 1:
        pts = [
            (
                pts[i][0] * (1.0 - t) + pts[i + 1][0] * t,
                pts[i][1] * (1.0 - t) + pts[i + 1][1] * t,
            )
            for i in range(len(pts) - 1)
        ]
    return pts[0]


def apply_velocity_jitter(
    points: list[tuple[float, float]],
    *,
    stddev: float,
    base_delay_ms: float = 12.0,
    rng: Random | None = None,
    min_delay_ms: float = 1.0,
) -> list[tuple[float, float, float]]:
    """Asocia un delay (ms) jitter a cada punto de la curva.

    Devuelve `(x, y, delay_ms)`. Usa una distribución gaussiana multiplicativa
    sobre `base_delay_ms` con desviación `stddev` (relativa al base, p.ej. 0.25).
    """
    if stddev < 0.0:
        raise ValueError("stddev debe ser >= 0")
    rng = rng if rng is not None else Random()  # noqa: S311

    result: list[tuple[float, float, float]] = []
    for x, y in points:
        factor = rng.gauss(1.0, stddev)
        delay = max(min_delay_ms, base_delay_ms * factor)
        result.append((x, y, delay))
    return result


def compute_overshoot(
    end: tuple[float, float],
    *,
    max_pixels: int,
    rng: Random | None = None,
) -> tuple[float, float]:
    """Devuelve un punto cercano a `end` que simula un overshoot del cursor.

    El offset tiene magnitud entre 30% y 100% de `max_pixels` y dirección
    uniforme en [0, 2π).
    """
    if max_pixels <= 0:
        raise ValueError("max_pixels debe ser > 0")
    rng = rng if rng is not None else Random()  # noqa: S311

    angle = rng.uniform(0.0, 2.0 * math.pi)
    radius = rng.uniform(max_pixels * 0.3, float(max_pixels))
    return (end[0] + radius * math.cos(angle), end[1] + radius * math.sin(angle))
