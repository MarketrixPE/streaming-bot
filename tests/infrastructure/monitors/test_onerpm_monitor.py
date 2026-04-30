"""Tests del ``OneRPMMonitor`` (sin Playwright real)."""

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
from streaming_bot.infrastructure.monitors.onerpm_monitor import (
    ONERPM_DASHBOARD,
    ONERPM_EARNINGS,
    ONERPM_SIGNIN,
    OneRPMMonitor,
)

FactoryFn = Callable[..., Any]


def _build(
    *,
    driver: Any,
    fingerprint: Fingerprint,
    cache: BaselineCache,
    logger: structlog.stdlib.BoundLogger,
    storage_path: Path,
    revenue_drop_pct: float = -40.0,
) -> OneRPMMonitor:
    return OneRPMMonitor(
        browser_driver=driver,
        fingerprint=fingerprint,
        storage_state_path=storage_path,
        logger=logger,
        baseline_cache=cache,
        revenue_drop_threshold_pct=revenue_drop_pct,
    )


def test_scan_dashboard_html_detects_payment_hold(
    fixture_onerpm_dashboard_html: str,
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
        storage_path=tmp_path / "orpm.json",
    )
    alerts = monitor.scan_dashboard_html(fixture_onerpm_dashboard_html)
    categories = {a.category for a in alerts}
    assert AlertCategory.PAYMENT_HOLD in categories
    assert any(a.severity == AlertSeverity.CRITICAL for a in alerts)


def test_scan_dashboard_html_clean_no_alerts(
    fixture_onerpm_dashboard_clean_html: str,
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
        storage_path=tmp_path / "orpm.json",
    )
    alerts = monitor.scan_dashboard_html(fixture_onerpm_dashboard_clean_html)
    assert alerts == []


def test_scan_earnings_html_detects_revenue_drop(
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    for value in (4000.0, 4200.0, 4100.0, 3900.0):
        baseline_cache_tmp.record_metric(DistributorPlatform.ONERPM, "earnings_monthly", value)

    driver, _ = fake_browser_factory({})
    monitor = _build(
        driver=driver,
        fingerprint=dummy_fingerprint,
        cache=baseline_cache_tmp,
        logger=test_logger,
        storage_path=tmp_path / "orpm.json",
        revenue_drop_pct=-40.0,
    )
    html_low = """
    <html><body>
      <div class="earnings-total" data-testid="earnings-total">$ 1,000.00</div>
    </body></html>
    """
    alerts = monitor.scan_earnings_html(html_low)
    assert any(a.category == AlertCategory.REVENUE_DROP for a in alerts)


def test_scan_earnings_html_no_drop_within_threshold(
    fixture_onerpm_dashboard_clean_html: str,
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    for value in (4200.0, 4100.0, 4250.0):
        baseline_cache_tmp.record_metric(DistributorPlatform.ONERPM, "earnings_monthly", value)
    driver, _ = fake_browser_factory({})
    monitor = _build(
        driver=driver,
        fingerprint=dummy_fingerprint,
        cache=baseline_cache_tmp,
        logger=test_logger,
        storage_path=tmp_path / "orpm.json",
    )
    alerts = monitor.scan_earnings_html(fixture_onerpm_dashboard_clean_html)
    assert all(a.category != AlertCategory.REVENUE_DROP for a in alerts)


@pytest.mark.asyncio
async def test_login_and_scrape_collects_alerts(
    fixture_onerpm_dashboard_html: str,
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    driver, session = fake_browser_factory(
        {
            ONERPM_DASHBOARD: fixture_onerpm_dashboard_html,
            ONERPM_EARNINGS: fixture_onerpm_dashboard_html,
        },
        current_url="https://app.onerpm.com/dashboard",
    )
    monitor = _build(
        driver=driver,
        fingerprint=dummy_fingerprint,
        cache=baseline_cache_tmp,
        logger=test_logger,
        storage_path=tmp_path / "orpm.json",
    )
    alerts = await monitor.login_and_scrape()
    assert any(a.category == AlertCategory.PAYMENT_HOLD for a in alerts)
    assert ONERPM_DASHBOARD in session.visit_log
    assert ONERPM_EARNINGS in session.visit_log


@pytest.mark.asyncio
async def test_is_authenticated_detects_login_visible(
    dummy_fingerprint: Fingerprint,
    test_logger: structlog.stdlib.BoundLogger,
    baseline_cache_tmp: BaselineCache,
    tmp_path: Path,
    fake_browser_factory: FactoryFn,
) -> None:
    driver, _ = fake_browser_factory(
        {ONERPM_SIGNIN: "<html><body><form action='/login'></form></body></html>"},
        visible_selectors={"form[action*='login'], input[type='password']"},
        current_url="https://app.onerpm.com/login",
    )
    monitor = _build(
        driver=driver,
        fingerprint=dummy_fingerprint,
        cache=baseline_cache_tmp,
        logger=test_logger,
        storage_path=tmp_path / "orpm.json",
    )
    assert await monitor.is_authenticated() is False
