"""Tests de las utilidades puras de jitter."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from streaming_bot.application.scheduler.jitter import (
    apply_target_jitter,
    apply_time_jitter,
    should_skip_today,
)


class TestApplyTargetJitter:
    def test_target_zero_returns_zero(self) -> None:
        assert apply_target_jitter(0, pct=0.5) == 0

    def test_pct_zero_returns_target(self) -> None:
        assert apply_target_jitter(100, pct=0.0) == 100

    def test_jitter_is_bounded(self) -> None:
        rng = random.Random(7)
        for _ in range(200):
            value = apply_target_jitter(100, pct=0.15, rng=rng)
            assert 85 <= value <= 115

    def test_deterministic_with_seed(self) -> None:
        rng_a = random.Random(42)
        rng_b = random.Random(42)
        seq_a = [apply_target_jitter(50, pct=0.20, rng=rng_a) for _ in range(20)]
        seq_b = [apply_target_jitter(50, pct=0.20, rng=rng_b) for _ in range(20)]
        assert seq_a == seq_b

    def test_negative_target_raises(self) -> None:
        with pytest.raises(ValueError, match="target negativo"):
            apply_target_jitter(-1)

    def test_negative_pct_raises(self) -> None:
        with pytest.raises(ValueError, match="pct negativo"):
            apply_target_jitter(10, pct=-0.1)


class TestApplyTimeJitter:
    def test_zero_max_returns_same(self) -> None:
        base = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)
        assert apply_time_jitter(base, max_minutes=0) == base

    def test_jitter_bounded(self) -> None:
        rng = random.Random(13)
        base = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)
        for _ in range(100):
            shifted = apply_time_jitter(base, max_minutes=12, rng=rng)
            delta = abs((shifted - base).total_seconds())
            assert delta <= 12 * 60 + 1  # tolerancia 1s por redondeo

    def test_deterministic_with_seed(self) -> None:
        base = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)
        rng_a = random.Random(99)
        rng_b = random.Random(99)
        a = [apply_time_jitter(base, 10, rng=rng_a) for _ in range(10)]
        b = [apply_time_jitter(base, 10, rng=rng_b) for _ in range(10)]
        assert a == b

    def test_negative_max_raises(self) -> None:
        base = datetime(2026, 5, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="max_minutes negativo"):
            apply_time_jitter(base, max_minutes=-1)

    def test_returns_datetime_instance(self) -> None:
        base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
        result = apply_time_jitter(base, max_minutes=5, rng=random.Random(0))
        assert isinstance(result, datetime)
        assert result - base <= timedelta(minutes=6)


class TestShouldSkipToday:
    def test_zero_chance_never_skips(self) -> None:
        rng = random.Random(0)
        assert not any(should_skip_today(rng, skip_chance=0.0) for _ in range(100))

    def test_full_chance_always_skips(self) -> None:
        rng = random.Random(0)
        assert all(should_skip_today(rng, skip_chance=1.0) for _ in range(100))

    def test_deterministic_with_seed(self) -> None:
        rng_a = random.Random(123)
        rng_b = random.Random(123)
        seq_a = [should_skip_today(rng_a, 0.5) for _ in range(20)]
        seq_b = [should_skip_today(rng_b, 0.5) for _ in range(20)]
        assert seq_a == seq_b

    def test_invalid_chance_raises(self) -> None:
        rng = random.Random(0)
        with pytest.raises(ValueError, match="skip_chance"):
            should_skip_today(rng, skip_chance=1.5)
        with pytest.raises(ValueError, match="skip_chance"):
            should_skip_today(rng, skip_chance=-0.1)

    def test_skip_chance_approximate_distribution(self) -> None:
        """Con 5% chance, la frecuencia se acerca al 5% en muestras grandes."""
        rng = random.Random(1)
        skips = sum(should_skip_today(rng, 0.05) for _ in range(2000))
        assert 50 <= skips <= 150  # ±50% sobre 100 esperados es razonable
