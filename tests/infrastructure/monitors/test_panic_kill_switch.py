"""Tests del ``FilesystemPanicKillSwitch``."""

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
from streaming_bot.infrastructure.monitors.panic_kill_switch import (
    FilesystemPanicKillSwitch,
    is_kill_switch_marker_present,
)


@pytest.fixture()
def kill_switch(tmp_path: Path) -> FilesystemPanicKillSwitch:
    return FilesystemPanicKillSwitch(
        marker_path=tmp_path / ".kill_switch_active",
        audit_log_path=tmp_path / "audit.log",
        logger=structlog.get_logger("test"),
    )


@pytest.fixture()
def sample_alert() -> DistributorAlert:
    return DistributorAlert(
        platform=DistributorPlatform.SPOTIFY_FOR_ARTISTS,
        severity=AlertSeverity.CRITICAL,
        category=AlertCategory.FILTERED_STREAMS,
        detected_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        message="Streams filtrados detectados",
        affected_song_titles=("song-a", "song-b"),
        raw_evidence="Some streams may have been filtered",
    )


@pytest.mark.asyncio
async def test_trigger_creates_marker_file(
    kill_switch: FilesystemPanicKillSwitch,
    sample_alert: DistributorAlert,
    tmp_path: Path,
) -> None:
    marker = tmp_path / ".kill_switch_active"
    assert not marker.exists()
    await kill_switch.trigger(reason="test", triggering_alert=sample_alert)
    assert marker.exists(), "marker debe crearse"
    payload = marker.read_text(encoding="utf-8")
    assert "filtered_streams" in payload
    assert "test" in payload


@pytest.mark.asyncio
async def test_is_active_true_after_trigger(
    kill_switch: FilesystemPanicKillSwitch,
) -> None:
    assert await kill_switch.is_active() is False
    await kill_switch.trigger(reason="critical alert", triggering_alert=None)
    assert await kill_switch.is_active() is True


@pytest.mark.asyncio
async def test_reset_deletes_marker_with_audit(
    kill_switch: FilesystemPanicKillSwitch,
    tmp_path: Path,
) -> None:
    await kill_switch.trigger(reason="boom")
    assert (tmp_path / ".kill_switch_active").exists()
    await kill_switch.reset(authorized_by="ops-lead", justification="false positive verified")
    assert not (tmp_path / ".kill_switch_active").exists()
    audit_text = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert "trigger" in audit_text
    assert "reset" in audit_text
    assert "ops-lead" in audit_text


@pytest.mark.asyncio
async def test_reset_requires_authorized_by_and_justification(
    kill_switch: FilesystemPanicKillSwitch,
) -> None:
    with pytest.raises(ValueError, match="authorized_by"):
        await kill_switch.reset(authorized_by="   ", justification="ok")
    with pytest.raises(ValueError, match="justification"):
        await kill_switch.reset(authorized_by="ops-lead", justification="")


@pytest.mark.asyncio
async def test_subscribe_callback_invoked_once_on_trigger(
    kill_switch: FilesystemPanicKillSwitch,
    sample_alert: DistributorAlert,
) -> None:
    invocations: list[tuple[DistributorAlert | None, str]] = []

    async def callback(alert: DistributorAlert | None, reason: str) -> None:
        invocations.append((alert, reason))

    kill_switch.subscribe_callback(callback)

    await kill_switch.trigger(reason="first", triggering_alert=sample_alert)
    await kill_switch.trigger(reason="second", triggering_alert=sample_alert)

    assert len(invocations) == 1, "callback solo debe correr la primera vez"
    captured_alert, captured_reason = invocations[0]
    assert captured_reason == "first"
    assert captured_alert is sample_alert


@pytest.mark.asyncio
async def test_callback_failure_does_not_break_trigger(
    kill_switch: FilesystemPanicKillSwitch,
) -> None:
    def buggy_callback(_alert: Any, _reason: str) -> None:
        raise RuntimeError("oops")

    kill_switch.subscribe_callback(buggy_callback)
    await kill_switch.trigger(reason="resilient")
    assert await kill_switch.is_active() is True


def test_helper_marker_check(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    assert is_kill_switch_marker_present(marker) is False
    marker.write_text("x", encoding="utf-8")
    assert is_kill_switch_marker_present(marker) is True
