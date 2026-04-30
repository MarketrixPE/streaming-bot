"""Tests del ``BaselineCache``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from streaming_bot.domain.ports.distributor_monitor import DistributorPlatform
from streaming_bot.infrastructure.monitors.baseline_cache import BaselineCache


def _build_cache(tmp_path: Path, max_samples: int = 12) -> BaselineCache:
    return BaselineCache(
        cache_path=tmp_path / "baseline.json",
        max_samples_per_metric=max_samples,
        logger=structlog.get_logger("test_baseline"),
    )


def test_record_and_get_recent_returns_chronological(tmp_path: Path) -> None:
    cache = _build_cache(tmp_path)
    base = datetime(2025, 1, 1, tzinfo=UTC)
    for i in range(5):
        cache.record_metric(
            DistributorPlatform.DISTROKID,
            "earnings_monthly",
            value=100.0 + i,
            when=base + timedelta(days=i),
        )
    samples = cache.get_recent(DistributorPlatform.DISTROKID, "earnings_monthly", last_n=3)
    assert [s.value for s in samples] == [102.0, 103.0, 104.0]


def test_compute_delta_pct_no_history_returns_none(tmp_path: Path) -> None:
    cache = _build_cache(tmp_path)
    delta = cache.compute_delta_pct(
        DistributorPlatform.ONERPM, "earnings_monthly", current_value=100.0
    )
    assert delta is None


def test_compute_delta_pct_with_history(tmp_path: Path) -> None:
    cache = _build_cache(tmp_path)
    base = datetime(2025, 1, 1, tzinfo=UTC)
    for i, value in enumerate([100, 110, 90, 105]):
        cache.record_metric(
            DistributorPlatform.DISTROKID,
            "earnings_monthly",
            value=float(value),
            when=base + timedelta(days=i),
        )
    # Mediana de [100, 110, 90, 105] = 102.5
    delta = cache.compute_delta_pct(
        DistributorPlatform.DISTROKID, "earnings_monthly", current_value=51.25
    )
    assert delta is not None
    assert -51.0 < delta < -49.0


def test_persistence_across_instances(tmp_path: Path) -> None:
    cache1 = _build_cache(tmp_path)
    cache1.record_metric(DistributorPlatform.DISTROKID, "earnings_monthly", 100.0)
    cache1.record_metric(DistributorPlatform.DISTROKID, "earnings_monthly", 200.0)

    # Reabrimos: la persistencia debe haber funcionado.
    cache2 = _build_cache(tmp_path)
    samples = cache2.get_recent(DistributorPlatform.DISTROKID, "earnings_monthly")
    assert [s.value for s in samples] == [100.0, 200.0]


def test_max_samples_trims_oldest(tmp_path: Path) -> None:
    cache = _build_cache(tmp_path, max_samples=3)
    base = datetime(2025, 1, 1, tzinfo=UTC)
    for i in range(5):
        cache.record_metric(
            DistributorPlatform.DISTROKID,
            "earnings_monthly",
            value=float(i),
            when=base + timedelta(days=i),
        )
    samples = cache.get_recent(DistributorPlatform.DISTROKID, "earnings_monthly", last_n=10)
    assert [s.value for s in samples] == [2.0, 3.0, 4.0]


def test_reset_metric_clears_history(tmp_path: Path) -> None:
    cache = _build_cache(tmp_path)
    cache.record_metric(DistributorPlatform.DISTROKID, "earnings_monthly", 1.0)
    cache.reset_metric(DistributorPlatform.DISTROKID, "earnings_monthly")
    assert cache.get_recent(DistributorPlatform.DISTROKID, "earnings_monthly") == []


def test_zero_baseline_returns_none_delta(tmp_path: Path) -> None:
    cache = _build_cache(tmp_path)
    cache.record_metric(DistributorPlatform.ONERPM, "earnings_monthly", 0.0)
    delta = cache.compute_delta_pct(
        DistributorPlatform.ONERPM, "earnings_monthly", current_value=10.0
    )
    assert delta is None
