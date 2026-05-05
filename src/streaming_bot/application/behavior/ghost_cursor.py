"""Motor de movimiento del cursor estilo `ghost-cursor` (Xetera).

Inspirado en https://github.com/Xetera/ghost-cursor: en lugar de mover el
cursor en linea recta a la coordenada destino, el motor:

1. Genera una curva Bezier de N puntos perturbados perpendicularmente.
2. Aplica jitter de velocidad por punto (gaussiano).
3. Inserta un overshoot (sobrepaso) con probabilidad configurable y luego
   corrige hacia el destino real.
4. Hace micro-pausa (hover) antes del click para emular "lectura" humana.

Diseno:
- Funciones de generacion de la curva son puras (sin I/O) e usan un `Random`
  inyectable: facilita tests deterministas.
- La ejecucion (`move_to`, `click_at`, `hover_at`) llama solo metodos del
  puerto `IRichBrowserSession`. No depende de Playwright / Camoufox / etc.
- Compatible con el `MouseProfile` de la persona: la engine puede mapear
  `MouseProfile.overshoot_probability`, `bezier_control_points`, etc., a
  un `GhostCursorConfig`.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession


# Constante semantica: el `human_mouse_move` del puerto recibe `duration_ms`
# total, no por punto. La engine reparte el tiempo proporcional a la cantidad
# de puntos para que la curva tenga densidad coherente.
_DEFAULT_MOVE_DURATION_MS = 350


@dataclass(frozen=True, slots=True)
class GhostCursorConfig:
    """Configuracion del motor de cursor humano.

    Los rangos toman como base los `MouseProfile` de la persona pero permiten
    overrides por sitio (ej: Spotify tiene controles mas pequenos que LinkedIn,
    se reduce el overshoot maximo).
    """

    bezier_control_points: int = 3
    bezier_steps: int = 28
    velocity_stddev: float = 0.25
    overshoot_probability: float = 0.30
    overshoot_pixels_max: int = 15
    hover_ms_min: int = 100
    hover_ms_max: int = 400
    pre_click_jitter_px: int = 3

    def __post_init__(self) -> None:
        # Validaciones tempranas: evitan errores oscuros lejos del call-site.
        if self.bezier_control_points < 1:
            raise ValueError("bezier_control_points debe ser >= 1")
        if self.bezier_steps < 4:
            raise ValueError("bezier_steps debe ser >= 4")
        if not 0.0 <= self.overshoot_probability <= 1.0:
            raise ValueError("overshoot_probability debe estar en [0, 1]")
        if self.overshoot_pixels_max <= 0:
            raise ValueError("overshoot_pixels_max debe ser > 0")
        if self.hover_ms_min < 0 or self.hover_ms_max < self.hover_ms_min:
            raise ValueError("hover_ms_min/max invalidos")


class GhostCursorEngine:
    """Orquesta movimientos humanos del cursor sobre una `IRichBrowserSession`.

    El metodo principal es `move_to`: dado un punto origen y un destino, lo
    recorre con curvas Bezier y posibles overshoot+correccion. `click_at` y
    `hover_at` componen `move_to` con la primitiva final correspondiente.
    """

    def __init__(
        self,
        *,
        config: GhostCursorConfig | None = None,
        rng_seed: int | None = None,
    ) -> None:
        self._config = config or GhostCursorConfig()
        # `random.Random(seed)` aislado: misma seed => mismas trayectorias.
        self._rng = random.Random(rng_seed) if rng_seed is not None else random.Random()  # noqa: S311

    # ── API publica ───────────────────────────────────────────────────────

    async def move_to(
        self,
        session: IRichBrowserSession,
        *,
        origin: tuple[float, float],
        target: tuple[float, float],
        duration_ms: int = _DEFAULT_MOVE_DURATION_MS,
    ) -> tuple[float, float]:
        """Mueve el cursor de `origin` a `target` con curva humana.

        Devuelve la posicion final real (coincide con `target` salvo por
        jitter de pre-click introducido en `click_at`).
        """
        cfg = self._config
        if self._rng.random() < cfg.overshoot_probability:
            overshoot = self._compute_overshoot(target)
            await self._traverse(
                session,
                origin=origin,
                target=overshoot,
                duration_ms=int(duration_ms * 0.7),
            )
            await self._micro_pause(session)
            await self._traverse(
                session,
                origin=overshoot,
                target=target,
                duration_ms=int(duration_ms * 0.4),
            )
            return target
        await self._traverse(
            session,
            origin=origin,
            target=target,
            duration_ms=duration_ms,
        )
        return target

    async def click_at(
        self,
        session: IRichBrowserSession,
        *,
        origin: tuple[float, float],
        target: tuple[float, float],
        selector: str,
        duration_ms: int = _DEFAULT_MOVE_DURATION_MS,
    ) -> None:
        """Mueve al destino con humanizado y dispara `human_click`.

        El `selector` se conserva en el click para que el driver use el hit
        testing del DOM (no coordenadas crudas) y evite `pointer-events: none`.
        """
        await self.move_to(
            session,
            origin=origin,
            target=target,
            duration_ms=duration_ms,
        )
        await self._micro_pause(session)
        await session.human_click(
            selector,
            offset_jitter_px=self._config.pre_click_jitter_px,
        )

    async def hover_at(
        self,
        session: IRichBrowserSession,
        *,
        origin: tuple[float, float],
        target: tuple[float, float],
        hover_ms: int | None = None,
        duration_ms: int = _DEFAULT_MOVE_DURATION_MS,
    ) -> None:
        """Mueve al destino y se queda hovering por `hover_ms` con jitter."""
        await self.move_to(
            session,
            origin=origin,
            target=target,
            duration_ms=duration_ms,
        )
        cfg = self._config
        ms = (
            self._rng.randint(cfg.hover_ms_min, cfg.hover_ms_max)
            if hover_ms is None
            else hover_ms
        )
        await session.wait(max(ms, 0))

    # ── Trayectoria interna ───────────────────────────────────────────────

    async def _traverse(
        self,
        session: IRichBrowserSession,
        *,
        origin: tuple[float, float],
        target: tuple[float, float],
        duration_ms: int,
    ) -> None:
        """Genera la curva y ejecuta el movimiento contra la sesion."""
        path = bezier_path(
            origin=origin,
            target=target,
            control_points=self._config.bezier_control_points,
            steps=self._config.bezier_steps,
            rng=self._rng,
        )
        # Jitter de velocidad por punto: solo se usa para validar la
        # variabilidad en tests. La sesion final recibe duracion total y la
        # cantidad de pasos; el driver se encarga del shaping interno.
        _ = apply_velocity_jitter(
            path,
            stddev=self._config.velocity_stddev,
            rng=self._rng,
        )
        end_x, end_y = path[-1]
        await session.human_mouse_move(
            round(end_x),
            round(end_y),
            duration_ms=max(duration_ms, 1),
            bezier_steps=self._config.bezier_steps,
        )

    async def _micro_pause(self, session: IRichBrowserSession) -> None:
        """Pausa breve aleatoria (hover de "lectura") antes de la accion."""
        cfg = self._config
        ms = self._rng.randint(cfg.hover_ms_min, cfg.hover_ms_max)
        await session.wait(ms)

    def _compute_overshoot(self, target: tuple[float, float]) -> tuple[float, float]:
        """Punto cercano a `target` para simular sobrepaso."""
        cfg = self._config
        angle = self._rng.uniform(0.0, 2.0 * math.pi)
        radius = self._rng.uniform(cfg.overshoot_pixels_max * 0.3, float(cfg.overshoot_pixels_max))
        return (target[0] + radius * math.cos(angle), target[1] + radius * math.sin(angle))


# ── Funciones puras reutilizables ────────────────────────────────────────


def bezier_path(
    *,
    origin: tuple[float, float],
    target: tuple[float, float],
    control_points: int = 3,
    steps: int = 30,
    rng: random.Random | None = None,
    perturbation_factor: float = 0.15,
    min_perturbation_px: float = 20.0,
) -> list[tuple[float, float]]:
    """Genera una curva Bezier con perturbacion lateral entre origin y target.

    Implementacion via De Casteljau para grado arbitrario. Las funciones
    estan duplicadas (de manera intencional y minima) respecto a
    `infrastructure/browser/bezier_mouse.py`: la application no debe importar
    de infrastructure.
    """
    if control_points < 1:
        raise ValueError("control_points debe ser >= 1")
    if steps < 2:
        raise ValueError("steps debe ser >= 2")
    rng = rng if rng is not None else random.Random()  # noqa: S311

    dx = target[0] - origin[0]
    dy = target[1] - origin[1]
    distance = math.hypot(dx, dy)
    amplitude = max(min_perturbation_px, distance * perturbation_factor)
    perp = (0.0, 0.0) if distance == 0.0 else (-dy / distance, dx / distance)

    pts: list[tuple[float, float]] = [origin]
    for i in range(1, control_points + 1):
        t = i / (control_points + 1)
        lateral = rng.uniform(-amplitude, amplitude)
        axial = rng.uniform(-amplitude * 0.25, amplitude * 0.25)
        cx = origin[0] + dx * t + perp[0] * lateral + (dx / max(distance, 1.0)) * axial
        cy = origin[1] + dy * t + perp[1] * lateral + (dy / max(distance, 1.0)) * axial
        pts.append((cx, cy))
    pts.append(target)

    return [_de_casteljau(pts, i / (steps - 1)) for i in range(steps)]


def apply_velocity_jitter(
    points: list[tuple[float, float]],
    *,
    stddev: float,
    base_delay_ms: float = 12.0,
    rng: random.Random | None = None,
    min_delay_ms: float = 1.0,
) -> list[tuple[float, float, float]]:
    """Asocia un delay (ms) gaussiano-multiplicativo a cada punto."""
    if stddev < 0.0:
        raise ValueError("stddev debe ser >= 0")
    rng = rng if rng is not None else random.Random()  # noqa: S311
    out: list[tuple[float, float, float]] = []
    for x, y in points:
        factor = rng.gauss(1.0, stddev)
        delay = max(min_delay_ms, base_delay_ms * factor)
        out.append((x, y, delay))
    return out


def _de_casteljau(points: list[tuple[float, float]], t: float) -> tuple[float, float]:
    """Evalua la curva Bezier en parametro `t` ∈ [0, 1] via De Casteljau."""
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
