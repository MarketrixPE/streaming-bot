"""Tests del ``MonitorOrchestrator``."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import structlog

from streaming_bot.domain.ports.distributor_monitor import (
    AlertCategory,
    AlertSeverity,
    DistributorAlert,
    DistributorPlatform,
)
from streaming_bot.infrastructure.monitors.monitor_orchestrator import (
    MonitorOrchestrator,
)
from streaming_bot.infrastructure.monitors.panic_kill_switch import (
    FilesystemPanicKillSwitch,
)


class _StubMonitor:
    def __init__(
        self,
        platform: DistributorPlatform,
        scrape_alerts: list[DistributorAlert] | None = None,
        email_alerts: list[DistributorAlert] | None = None,
        scrape_exception: Exception | None = None,
        email_exception: Exception | None = None,
    ) -> None:
        self._platform = platform
        self._scrape_alerts = scrape_alerts or []
        self._email_alerts = email_alerts or []
        self._scrape_exc = scrape_exception
        self._email_exc = email_exception
        self.scrape_calls = 0
        self.email_calls = 0

    @property
    def platform(self) -> DistributorPlatform:
        return self._platform

    async def login_and_scrape(self) -> list[DistributorAlert]:
        self.scrape_calls += 1
        if self._scrape_exc is not None:
            raise self._scrape_exc
        return list(self._scrape_alerts)

    async def check_emails(self, since: datetime | None = None) -> list[DistributorAlert]:
        _ = since
        self.email_calls += 1
        if self._email_exc is not None:
            raise self._email_exc
        return list(self._email_alerts)

    async def is_authenticated(self) -> bool:
        return True


def _build_alert(
    *,
    severity: AlertSeverity,
    platform: DistributorPlatform = DistributorPlatform.SPOTIFY_FOR_ARTISTS,
    category: AlertCategory = AlertCategory.FILTERED_STREAMS,
) -> DistributorAlert:
    return DistributorAlert(
        platform=platform,
        severity=severity,
        category=category,
        detected_at=datetime(2026, 4, 1, tzinfo=UTC),
        message=f"{severity.value} alert",
    )


@pytest.fixture()
def kill_switch(tmp_path: Path) -> FilesystemPanicKillSwitch:
    return FilesystemPanicKillSwitch(
        marker_path=tmp_path / ".kill_switch_active",
        audit_log_path=tmp_path / "audit.log",
        logger=structlog.get_logger("test_orch"),
    )


@pytest.mark.asyncio
async def test_run_once_triggers_kill_switch_on_critical(
    kill_switch: FilesystemPanicKillSwitch,
) -> None:
    info = _StubMonitor(
        DistributorPlatform.ONERPM,
        scrape_alerts=[_build_alert(severity=AlertSeverity.INFO)],
    )
    critical = _StubMonitor(
        DistributorPlatform.SPOTIFY_FOR_ARTISTS,
        scrape_alerts=[_build_alert(severity=AlertSeverity.CRITICAL)],
    )

    triggered: list[Any] = []
    original_trigger = kill_switch.trigger

    async def spy_trigger(
        *,
        reason: str,
        triggering_alert: DistributorAlert | None = None,
    ) -> None:
        triggered.append((reason, triggering_alert))
        await original_trigger(reason=reason, triggering_alert=triggering_alert)

    kill_switch.trigger = spy_trigger  # type: ignore[method-assign]

    orchestrator = MonitorOrchestrator(
        monitors=[info, critical],
        kill_switch=kill_switch,
        logger=structlog.get_logger("test"),
        check_emails=False,
    )
    alerts = await orchestrator.run_once()
    assert len(alerts) == 2
    assert len(triggered) == 1, "kill_switch.trigger debe llamarse exactamente UNA vez"
    assert await kill_switch.is_active() is True


@pytest.mark.asyncio
async def test_run_once_no_critical_does_not_trigger(
    kill_switch: FilesystemPanicKillSwitch,
) -> None:
    monitor = _StubMonitor(
        DistributorPlatform.DISTROKID,
        scrape_alerts=[_build_alert(severity=AlertSeverity.WARNING)],
    )
    orchestrator = MonitorOrchestrator(
        monitors=[monitor],
        kill_switch=kill_switch,
        logger=structlog.get_logger("test"),
        check_emails=False,
    )
    await orchestrator.run_once()
    assert await kill_switch.is_active() is False


@pytest.mark.asyncio
async def test_failing_monitor_does_not_break_loop(
    kill_switch: FilesystemPanicKillSwitch,
) -> None:
    bad = _StubMonitor(
        DistributorPlatform.AICOM,
        scrape_exception=RuntimeError("boom"),
    )
    good = _StubMonitor(
        DistributorPlatform.ONERPM,
        scrape_alerts=[_build_alert(severity=AlertSeverity.WARNING)],
    )
    orchestrator = MonitorOrchestrator(
        monitors=[bad, good],
        kill_switch=kill_switch,
        logger=structlog.get_logger("test"),
        check_emails=False,
    )
    alerts = await orchestrator.run_once()
    assert len(alerts) == 1
    assert good.scrape_calls == 1
    assert bad.scrape_calls == 1
    assert await kill_switch.is_active() is False


@pytest.mark.asyncio
async def test_alert_handler_invoked_per_alert(
    kill_switch: FilesystemPanicKillSwitch,
) -> None:
    monitor = _StubMonitor(
        DistributorPlatform.DISTROKID,
        scrape_alerts=[
            _build_alert(severity=AlertSeverity.WARNING),
            _build_alert(severity=AlertSeverity.INFO),
        ],
    )
    received: list[DistributorAlert] = []

    async def handler(alert: DistributorAlert) -> None:
        received.append(alert)

    orchestrator = MonitorOrchestrator(
        monitors=[monitor],
        kill_switch=kill_switch,
        logger=structlog.get_logger("test"),
        alert_handler=handler,
        check_emails=False,
    )
    await orchestrator.run_once()
    assert len(received) == 2


@pytest.mark.asyncio
async def test_handler_failure_isolated(
    kill_switch: FilesystemPanicKillSwitch,
) -> None:
    monitor = _StubMonitor(
        DistributorPlatform.ONERPM,
        scrape_alerts=[_build_alert(severity=AlertSeverity.WARNING)],
    )

    def bad_handler(alert: DistributorAlert) -> None:
        _ = alert
        raise RuntimeError("handler down")

    orchestrator = MonitorOrchestrator(
        monitors=[monitor],
        kill_switch=kill_switch,
        logger=structlog.get_logger("test"),
        alert_handler=bad_handler,
        check_emails=False,
    )
    # No debe propagar la excepcion del handler.
    alerts = await orchestrator.run_once()
    assert len(alerts) == 1


@pytest.mark.asyncio
async def test_check_emails_executed_when_enabled(
    kill_switch: FilesystemPanicKillSwitch,
) -> None:
    monitor = _StubMonitor(
        DistributorPlatform.DISTROKID,
        scrape_alerts=[],
        email_alerts=[_build_alert(severity=AlertSeverity.CRITICAL)],
    )
    orchestrator = MonitorOrchestrator(
        monitors=[monitor],
        kill_switch=kill_switch,
        logger=structlog.get_logger("test"),
        check_emails=True,
    )
    alerts = await orchestrator.run_once()
    assert monitor.scrape_calls == 1
    assert monitor.email_calls == 1
    assert len(alerts) == 1
    assert await kill_switch.is_active() is True
