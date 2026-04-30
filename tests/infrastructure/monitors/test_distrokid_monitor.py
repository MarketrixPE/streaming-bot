"""Tests del ``DistroKidMonitor`` (sin browser real)."""

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
from streaming_bot.infrastructure.monitors.distrokid_monitor import (
    DISTROKID_BANK,
    DISTROKID_DASHBOARD,
    DISTROKID_SIGNIN,
    DistroKidMonitor,
)

FactoryFn = Callable[..., Any]


def _build_monitor(
    *,
    browser_driver: Any,
    fingerprint: Fingerprint,
    storage_path: Path,
    baseline_cache: BaselineCache,
    logger: structlog.stdlib.BoundLogger,
    revenue_drop_pct: float = -40.0,
) -> DistroKidMonitor:
    return DistroKidMonitor(
        browser_driver=browser_driver,
        fingerprint=fingerprint,
        storage_state_path=storage_path,
        logger=logger,
        baseline_cache=baseline_cache,
        revenue_drop_threshold_pct=revenue_drop_pct,
    )


def test_scan_dashboard_html_detects_account_review(
    fixture_distrokid_dashboard_html: str,
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    driver, _ = fake_browser_factory({})
    monitor = _build_monitor(
        browser_driver=driver,
        fingerprint=dummy_fingerprint,
        storage_path=tmp_path / "dk.json",
        baseline_cache=baseline_cache_tmp,
        logger=test_logger,
    )
    alerts = monitor.scan_dashboard_html(fixture_distrokid_dashboard_html)
    categories = {a.category for a in alerts}
    severities = {a.severity for a in alerts}
    assert AlertCategory.ACCOUNT_REVIEW in categories
    assert AlertCategory.STREAM_MANIPULATION in categories or (
        AlertCategory.FILTERED_STREAMS in categories
    )
    assert AlertSeverity.CRITICAL in severities


def test_scan_dashboard_html_clean_returns_empty(
    fixture_distrokid_dashboard_clean_html: str,
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    driver, _ = fake_browser_factory({})
    monitor = _build_monitor(
        browser_driver=driver,
        fingerprint=dummy_fingerprint,
        storage_path=tmp_path / "dk.json",
        baseline_cache=baseline_cache_tmp,
        logger=test_logger,
    )
    alerts = monitor.scan_dashboard_html(fixture_distrokid_dashboard_clean_html)
    assert alerts == []


def test_scan_earnings_html_detects_drop_over_threshold(
    fixture_distrokid_dashboard_clean_html: str,
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    # Sembramos baseline con ~2300 USD historicos (mediana ~2300).
    for value in (2300.0, 2400.0, 2200.0, 2500.0):
        baseline_cache_tmp.record_metric(DistributorPlatform.DISTROKID, "earnings_monthly", value)

    driver, _ = fake_browser_factory({})
    monitor = _build_monitor(
        browser_driver=driver,
        fingerprint=dummy_fingerprint,
        storage_path=tmp_path / "dk.json",
        baseline_cache=baseline_cache_tmp,
        logger=test_logger,
        revenue_drop_pct=-40.0,
    )
    # Las filas de earnings_clean suman 2352.50 -> sin drop.
    alerts_clean = monitor.scan_earnings_html(fixture_distrokid_dashboard_clean_html)
    assert alerts_clean == []

    # Forzamos un HTML con earnings muy bajos (-90%).
    low_html = """
    <html><body><table>
      <tr><td>Spotify</td><td>$50.00</td></tr>
      <tr><td>Apple</td><td>$30.00</td></tr>
    </table></body></html>
    """
    alerts_drop = monitor.scan_earnings_html(low_html)
    assert any(a.category == AlertCategory.REVENUE_DROP for a in alerts_drop)
    assert any(a.severity == AlertSeverity.CRITICAL for a in alerts_drop)


def test_scan_earnings_html_no_alert_with_short_history(
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    """Sin baseline previo, no se puede calcular delta -> no alerta."""
    driver, _ = fake_browser_factory({})
    monitor = _build_monitor(
        browser_driver=driver,
        fingerprint=dummy_fingerprint,
        storage_path=tmp_path / "dk.json",
        baseline_cache=baseline_cache_tmp,
        logger=test_logger,
    )
    html = "<table><tr><td>$10.00</td></tr></table>"
    alerts = monitor.scan_earnings_html(html)
    assert alerts == []


@pytest.mark.asyncio
async def test_login_and_scrape_flows_through_pages(
    fixture_distrokid_dashboard_html: str,
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    driver, session = fake_browser_factory(
        {
            DISTROKID_DASHBOARD: fixture_distrokid_dashboard_html,
            DISTROKID_BANK: fixture_distrokid_dashboard_html,
            "https://distrokid.com/myaccount/": fixture_distrokid_dashboard_html,
        },
        storage_state={"cookies": [{"name": "x", "value": "y", "domain": "distrokid.com"}]},
        current_url="https://distrokid.com/dashboard/",
    )
    monitor = _build_monitor(
        browser_driver=driver,
        fingerprint=dummy_fingerprint,
        storage_path=tmp_path / "dk.json",
        baseline_cache=baseline_cache_tmp,
        logger=test_logger,
    )

    alerts = await monitor.login_and_scrape()
    assert any(a.category == AlertCategory.ACCOUNT_REVIEW for a in alerts)
    # Verificamos que paso por las paginas esperadas.
    assert DISTROKID_DASHBOARD in session.visit_log
    assert DISTROKID_BANK in session.visit_log


@pytest.mark.asyncio
async def test_is_authenticated_detects_login_form(
    fixture_distrokid_signin_html: str,
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    driver, _session = fake_browser_factory(
        {DISTROKID_SIGNIN: fixture_distrokid_signin_html},
        visible_selectors={"form[action*='signin'], input[name='email'][type='email']"},
        current_url="https://distrokid.com/signin/",
    )
    monitor = _build_monitor(
        browser_driver=driver,
        fingerprint=dummy_fingerprint,
        storage_path=tmp_path / "dk.json",
        baseline_cache=baseline_cache_tmp,
        logger=test_logger,
    )
    assert await monitor.is_authenticated() is False


@pytest.mark.asyncio
async def test_is_authenticated_returns_true_when_redirected_to_dashboard(
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    driver, _session = fake_browser_factory(
        {DISTROKID_SIGNIN: "<html></html>"},
        current_url="https://distrokid.com/dashboard/",
    )
    monitor = _build_monitor(
        browser_driver=driver,
        fingerprint=dummy_fingerprint,
        storage_path=tmp_path / "dk.json",
        baseline_cache=baseline_cache_tmp,
        logger=test_logger,
    )
    assert await monitor.is_authenticated() is True
