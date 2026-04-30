"""Tests del ``SpotifyForArtistsMonitor`` (CRITICO)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import structlog

from streaming_bot.domain.ports.distributor_monitor import (
    AlertCategory,
    AlertSeverity,
    DistributorPlatform,
)
from streaming_bot.domain.value_objects import Fingerprint
from streaming_bot.infrastructure.monitors.baseline_cache import BaselineCache
from streaming_bot.infrastructure.monitors.spotify_for_artists_monitor import (
    SpotifyForArtistsMonitor,
)

ARTIST_ID = "abc123"
HOME_URL = f"https://artists.spotify.com/c/artist/{ARTIST_ID}/home"
STATS_URL = f"https://artists.spotify.com/c/artist/{ARTIST_ID}/stats"
AUDIENCE_URL = f"https://artists.spotify.com/c/artist/{ARTIST_ID}/audience"

FactoryFn = Callable[..., Any]


def _build(
    *,
    driver: Any,
    fingerprint: Fingerprint,
    cache: BaselineCache,
    logger: structlog.stdlib.BoundLogger,
    storage_path: Path,
    streams_drop_pct: float = -30.0,
    listeners_drop_pct: float = -30.0,
) -> SpotifyForArtistsMonitor:
    return SpotifyForArtistsMonitor(
        browser_driver=driver,
        fingerprint=fingerprint,
        storage_state_path=storage_path,
        logger=logger,
        baseline_cache=cache,
        artist_id=ARTIST_ID,
        streams_drop_threshold_pct=streams_drop_pct,
        listeners_drop_threshold_pct=listeners_drop_pct,
    )


def test_artist_id_required(
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    driver, _ = fake_browser_factory({})
    with pytest.raises(ValueError, match="artist_id"):
        SpotifyForArtistsMonitor(
            browser_driver=driver,
            fingerprint=dummy_fingerprint,
            storage_state_path=tmp_path / "s4a.json",
            logger=test_logger,
            baseline_cache=baseline_cache_tmp,
            artist_id="",
        )


def test_scan_notifications_detects_filtered_streams_banner(
    fixture_spotify_stats_html: str,
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    driver, _ = fake_browser_factory({})
    monitor = _build(
        driver=driver,
        fingerprint=dummy_fingerprint,
        cache=baseline_cache_tmp,
        logger=test_logger,
        storage_path=tmp_path / "s4a.json",
    )
    alerts = monitor.scan_notifications_html(fixture_spotify_stats_html)
    categories = {a.category for a in alerts}
    assert AlertCategory.FILTERED_STREAMS in categories
    assert any(a.severity == AlertSeverity.CRITICAL for a in alerts)


def test_scan_stats_html_records_baseline_and_no_alert_first_run(
    fixture_spotify_stats_clean_html: str,
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    driver, _ = fake_browser_factory({})
    monitor = _build(
        driver=driver,
        fingerprint=dummy_fingerprint,
        cache=baseline_cache_tmp,
        logger=test_logger,
        storage_path=tmp_path / "s4a.json",
    )
    alerts = monitor.scan_stats_html(fixture_spotify_stats_clean_html)
    assert all(a.category != AlertCategory.SUDDEN_STREAM_DROP for a in alerts)
    samples = baseline_cache_tmp.get_recent(DistributorPlatform.SPOTIFY_FOR_ARTISTS, "streams_28d")
    assert samples and samples[-1].value == 85_000.0


def test_scan_stats_detects_sudden_drop_with_history(
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    for v in (80_000.0, 82_000.0, 85_000.0, 79_000.0):
        baseline_cache_tmp.record_metric(DistributorPlatform.SPOTIFY_FOR_ARTISTS, "streams_28d", v)
    html = """
    <html><body>
      <section>
        <div data-testid="streams-28-day"><span data-testid="value">10,000</span></div>
      </section>
    </body></html>
    """
    driver, _ = fake_browser_factory({})
    monitor = _build(
        driver=driver,
        fingerprint=dummy_fingerprint,
        cache=baseline_cache_tmp,
        logger=test_logger,
        storage_path=tmp_path / "s4a.json",
    )
    alerts = monitor.scan_stats_html(html)
    assert any(a.category == AlertCategory.SUDDEN_STREAM_DROP for a in alerts)
    drop_alert = next(a for a in alerts if a.category == AlertCategory.SUDDEN_STREAM_DROP)
    assert drop_alert.severity == AlertSeverity.CRITICAL


def test_scan_audience_detects_listeners_drop(
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    for v in (20_000.0, 21_000.0, 19_500.0):
        baseline_cache_tmp.record_metric(
            DistributorPlatform.SPOTIFY_FOR_ARTISTS, "monthly_listeners", v
        )
    html = """
    <html><body>
      <div data-testid="monthly-listeners"><span data-testid="value">3,000</span></div>
    </body></html>
    """
    driver, _ = fake_browser_factory({})
    monitor = _build(
        driver=driver,
        fingerprint=dummy_fingerprint,
        cache=baseline_cache_tmp,
        logger=test_logger,
        storage_path=tmp_path / "s4a.json",
    )
    alerts = monitor.scan_audience_html(html)
    assert any(a.category == AlertCategory.SUDDEN_STREAM_DROP for a in alerts)


@pytest.mark.asyncio
async def test_login_and_scrape_visits_home_stats_audience(
    fixture_spotify_stats_html: str,
    fixture_spotify_stats_clean_html: str,
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    driver, session = fake_browser_factory(
        {
            HOME_URL: fixture_spotify_stats_html,
            STATS_URL: fixture_spotify_stats_html,
            AUDIENCE_URL: fixture_spotify_stats_clean_html,
        },
        current_url=HOME_URL,
    )
    monitor = _build(
        driver=driver,
        fingerprint=dummy_fingerprint,
        cache=baseline_cache_tmp,
        logger=test_logger,
        storage_path=tmp_path / "s4a.json",
    )
    alerts = await monitor.login_and_scrape()
    assert any(a.category == AlertCategory.FILTERED_STREAMS for a in alerts)
    assert HOME_URL in session.visit_log
    assert STATS_URL in session.visit_log
    assert AUDIENCE_URL in session.visit_log


@pytest.mark.asyncio
async def test_is_authenticated_returns_false_on_login_redirect(
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    driver, _ = fake_browser_factory(
        {HOME_URL: "<html></html>"},
        current_url="https://accounts.spotify.com/login?continue=...",
    )
    monitor = _build(
        driver=driver,
        fingerprint=dummy_fingerprint,
        cache=baseline_cache_tmp,
        logger=test_logger,
        storage_path=tmp_path / "s4a.json",
    )
    assert await monitor.is_authenticated() is False
