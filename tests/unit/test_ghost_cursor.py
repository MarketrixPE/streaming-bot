"""Tests del `GhostCursorEngine`.

Estrategia:
- Usamos un mock async de `IRichBrowserSession` para verificar el orden y
  parametros de las llamadas (`human_mouse_move`, `wait`, `human_click`).
- Inyectamos `rng_seed` para reproducibilidad: el mismo seed produce la
  misma decision de overshoot/no-overshoot.
- Las funciones puras (`bezier_path`, `apply_velocity_jitter`) se testean
  directamente con propiedades matematicas (longitud, finitud, monotonia).
"""

from __future__ import annotations

import math
import random
from unittest.mock import AsyncMock

import pytest

from streaming_bot.application.behavior.ghost_cursor import (
    GhostCursorConfig,
    GhostCursorEngine,
    apply_velocity_jitter,
    bezier_path,
)


def _session_mock() -> AsyncMock:
    """Mock de `IRichBrowserSession` con primitivas humanas requeridas."""
    page = AsyncMock()
    page.human_mouse_move = AsyncMock(return_value=None)
    page.wait = AsyncMock(return_value=None)
    page.human_click = AsyncMock(return_value=None)
    return page


class TestBezierPath:
    """Tests de la funcion pura `bezier_path`."""

    def test_returns_requested_steps(self) -> None:
        path = bezier_path(
            origin=(0.0, 0.0),
            target=(100.0, 100.0),
            steps=15,
            rng=random.Random(1),
        )
        assert len(path) == 15

    def test_starts_at_origin_and_ends_at_target(self) -> None:
        origin = (10.0, 20.0)
        target = (110.0, 220.0)
        path = bezier_path(
            origin=origin,
            target=target,
            steps=20,
            rng=random.Random(42),
        )
        assert path[0] == pytest.approx(origin)
        assert path[-1] == pytest.approx(target)

    def test_intermediate_points_are_finite(self) -> None:
        path = bezier_path(
            origin=(0.0, 0.0),
            target=(500.0, -300.0),
            steps=30,
            rng=random.Random(99),
        )
        for x, y in path:
            assert math.isfinite(x)
            assert math.isfinite(y)

    def test_zero_distance_does_not_crash(self) -> None:
        path = bezier_path(
            origin=(50.0, 50.0),
            target=(50.0, 50.0),
            steps=10,
            rng=random.Random(0),
        )
        assert len(path) == 10
        for x, y in path:
            assert math.isfinite(x)
            assert math.isfinite(y)

    def test_invalid_control_points_raises(self) -> None:
        with pytest.raises(ValueError, match="control_points"):
            bezier_path(origin=(0.0, 0.0), target=(1.0, 1.0), control_points=0)

    def test_invalid_steps_raises(self) -> None:
        with pytest.raises(ValueError, match="steps"):
            bezier_path(origin=(0.0, 0.0), target=(1.0, 1.0), steps=1)

    def test_seed_reproducibility(self) -> None:
        a = bezier_path(
            origin=(0.0, 0.0),
            target=(200.0, 200.0),
            steps=12,
            rng=random.Random(123),
        )
        b = bezier_path(
            origin=(0.0, 0.0),
            target=(200.0, 200.0),
            steps=12,
            rng=random.Random(123),
        )
        assert a == b


class TestVelocityJitter:
    def test_returns_one_entry_per_point(self) -> None:
        points = [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]
        out = apply_velocity_jitter(points, stddev=0.25, rng=random.Random(1))
        assert len(out) == 3
        for entry in out:
            assert len(entry) == 3

    def test_delays_are_positive(self) -> None:
        points = [(0.0, 0.0)] * 50
        out = apply_velocity_jitter(points, stddev=0.5, rng=random.Random(7))
        for _x, _y, ms in out:
            assert ms >= 1.0

    def test_negative_stddev_raises(self) -> None:
        with pytest.raises(ValueError, match="stddev"):
            apply_velocity_jitter([(0.0, 0.0)], stddev=-0.1)


class TestGhostCursorEngine:
    """Tests de la orquestacion sobre `IRichBrowserSession`."""

    async def test_move_to_calls_human_mouse_move(self) -> None:
        engine = GhostCursorEngine(
            config=GhostCursorConfig(overshoot_probability=0.0),
            rng_seed=1,
        )
        page = _session_mock()
        await engine.move_to(page, origin=(0.0, 0.0), target=(100.0, 100.0))
        page.human_mouse_move.assert_called()
        x, y = page.human_mouse_move.call_args.args
        assert x == 100
        assert y == 100

    async def test_move_to_overshoots_when_probability_one(self) -> None:
        """Con overshoot_probability=1.0 debe haber 2 movimientos + pausa."""
        engine = GhostCursorEngine(
            config=GhostCursorConfig(overshoot_probability=1.0),
            rng_seed=1,
        )
        page = _session_mock()
        await engine.move_to(page, origin=(0.0, 0.0), target=(80.0, 80.0))
        # 2 segmentos: hacia overshoot y de overshoot a target.
        assert page.human_mouse_move.call_count == 2
        # Hubo al menos una micro-pausa entre el overshoot y la correccion.
        assert page.wait.call_count >= 1

    async def test_move_to_no_overshoot_when_probability_zero(self) -> None:
        engine = GhostCursorEngine(
            config=GhostCursorConfig(overshoot_probability=0.0),
            rng_seed=1,
        )
        page = _session_mock()
        await engine.move_to(page, origin=(0.0, 0.0), target=(80.0, 80.0))
        assert page.human_mouse_move.call_count == 1

    async def test_click_at_invokes_human_click(self) -> None:
        engine = GhostCursorEngine(
            config=GhostCursorConfig(overshoot_probability=0.0),
            rng_seed=1,
        )
        page = _session_mock()
        await engine.click_at(
            page,
            origin=(0.0, 0.0),
            target=(50.0, 50.0),
            selector="[data-testid='play-button']",
        )
        page.human_click.assert_called_once()
        # El selector se forwardea al driver.
        assert page.human_click.call_args.args[0] == "[data-testid='play-button']"

    async def test_hover_at_waits_after_move(self) -> None:
        engine = GhostCursorEngine(
            config=GhostCursorConfig(overshoot_probability=0.0),
            rng_seed=1,
        )
        page = _session_mock()
        await engine.hover_at(
            page,
            origin=(0.0, 0.0),
            target=(40.0, 40.0),
            hover_ms=250,
        )
        page.human_mouse_move.assert_called()
        page.wait.assert_called_with(250)

    async def test_seed_reproducibility_across_engines(self) -> None:
        page_a = _session_mock()
        page_b = _session_mock()
        engine_a = GhostCursorEngine(rng_seed=42)
        engine_b = GhostCursorEngine(rng_seed=42)
        await engine_a.move_to(page_a, origin=(0.0, 0.0), target=(100.0, 100.0))
        await engine_b.move_to(page_b, origin=(0.0, 0.0), target=(100.0, 100.0))
        assert page_a.human_mouse_move.call_count == page_b.human_mouse_move.call_count

    def test_invalid_config_raises(self) -> None:
        with pytest.raises(ValueError, match="bezier_control_points"):
            GhostCursorConfig(bezier_control_points=0)
        with pytest.raises(ValueError, match="bezier_steps"):
            GhostCursorConfig(bezier_steps=2)
        with pytest.raises(ValueError, match="overshoot_probability"):
            GhostCursorConfig(overshoot_probability=1.5)
        with pytest.raises(ValueError, match="overshoot_pixels_max"):
            GhostCursorConfig(overshoot_pixels_max=0)
        with pytest.raises(ValueError, match="hover_ms"):
            GhostCursorConfig(hover_ms_min=200, hover_ms_max=100)
