"""Tests del módulo bezier_mouse: trayectorias, jitter de velocidad y overshoot.

No requieren Playwright. Verifican propiedades matemáticas básicas y
reproducibilidad determinista cuando se inyecta un Random con seed.
"""

from __future__ import annotations

import math
from random import Random

import pytest

from streaming_bot.infrastructure.browser.bezier_mouse import (
    apply_velocity_jitter,
    bezier_curve,
    compute_overshoot,
)


class TestBezierCurve:
    def test_curve_starts_and_ends_at_endpoints(self) -> None:
        rng = Random(42)
        start = (10.0, 20.0)
        end = (300.0, 400.0)
        curve = bezier_curve(start, end, control_points=3, steps=30, rng=rng)

        assert curve[0] == pytest.approx(start, abs=1e-6)
        assert curve[-1] == pytest.approx(end, abs=1e-6)
        assert len(curve) == 30

    def test_curve_is_deterministic_with_same_seed(self) -> None:
        # Misma seed → curvas idénticas; semilla distinta → curvas distintas.
        a = bezier_curve((0, 0), (500, 200), steps=20, rng=Random(7))
        b = bezier_curve((0, 0), (500, 200), steps=20, rng=Random(7))
        c = bezier_curve((0, 0), (500, 200), steps=20, rng=Random(8))

        assert a == b
        assert a != c

    def test_intermediate_points_deviate_from_straight_line(self) -> None:
        # Una curva con perturbación debe alejarse de la recta start→end.
        start = (0.0, 0.0)
        end = (1000.0, 0.0)  # recta horizontal
        curve = bezier_curve(start, end, control_points=3, steps=20, rng=Random(1))
        max_deviation = max(abs(y) for _, y in curve)
        assert max_deviation > 5.0

    def test_invalid_steps_raises(self) -> None:
        with pytest.raises(ValueError):
            bezier_curve((0, 0), (10, 10), steps=1)

    def test_invalid_control_points_raises(self) -> None:
        with pytest.raises(ValueError):
            bezier_curve((0, 0), (10, 10), control_points=0)


class TestApplyVelocityJitter:
    def test_attaches_one_delay_per_point(self) -> None:
        points = [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]
        timed = apply_velocity_jitter(
            points,
            stddev=0.2,
            base_delay_ms=10.0,
            rng=Random(3),
        )
        assert len(timed) == len(points)
        for px, py, delay in timed:
            assert delay >= 1.0
            assert isinstance(px, float)
            assert isinstance(py, float)

    def test_negative_stddev_raises(self) -> None:
        with pytest.raises(ValueError):
            apply_velocity_jitter([(0.0, 0.0)], stddev=-0.1)

    def test_delays_vary_with_jitter(self) -> None:
        # Con stddev=0.5 los delays deben mostrar varianza > 0.
        timed = apply_velocity_jitter(
            [(i, 0.0) for i in range(50)],
            stddev=0.5,
            base_delay_ms=10.0,
            rng=Random(99),
        )
        delays = [d for _, _, d in timed]
        mean = sum(delays) / len(delays)
        variance = sum((d - mean) ** 2 for d in delays) / len(delays)
        assert variance > 0.5


class TestComputeOvershoot:
    def test_overshoot_within_radius(self) -> None:
        rng = Random(123)
        end = (500.0, 500.0)
        for _ in range(20):
            ox, oy = compute_overshoot(end, max_pixels=15, rng=rng)
            distance = math.hypot(ox - end[0], oy - end[1])
            # Debe estar entre 30% y 100% del max_pixels.
            assert 15 * 0.3 - 1e-6 <= distance <= 15 + 1e-6

    def test_overshoot_deterministic(self) -> None:
        a = compute_overshoot((100.0, 100.0), max_pixels=20, rng=Random(11))
        b = compute_overshoot((100.0, 100.0), max_pixels=20, rng=Random(11))
        assert a == b

    def test_invalid_max_pixels_raises(self) -> None:
        with pytest.raises(ValueError):
            compute_overshoot((0.0, 0.0), max_pixels=0)
