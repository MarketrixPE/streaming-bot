"""Tests del ``FeatureExtractor``.

Usamos fakes en lugar de ClickHouse / Postgres reales:
- ``FakeClickhouseRepo`` devuelve un ``_ClickhouseRollup`` predefinido.
- ``FakeSessionRepo`` devuelve sesiones sintéticas con duraciones fijas.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from streaming_bot.application.ml.feature_extractor import (
    FeatureExtractor,
    _ClickhouseRollup,
    _completion_rate,
    _repeat_track_ratio,
)
from streaming_bot.domain.history import SessionRecord


def _now() -> datetime:
    return datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


class FakeClickhouseRepo:
    def __init__(self, rollup: _ClickhouseRollup) -> None:
        self._rollup = rollup
        self.calls: list[tuple[str, datetime]] = []

    async def fetch_rollup(
        self,
        *,
        account_id: str,
        as_of: datetime,
    ) -> _ClickhouseRollup:
        self.calls.append((account_id, as_of))
        return self._rollup


class FakeSessionRepo:
    def __init__(self, sessions: list[SessionRecord]) -> None:
        self._sessions = sessions

    async def add(self, _record: SessionRecord) -> None:
        self._sessions.append(_record)

    async def get(self, _session_id: str) -> SessionRecord | None:
        return None

    async def list_for_account(
        self,
        _account_id: str,
        *,
        limit: int = 50,
    ) -> list[SessionRecord]:
        return self._sessions[:limit]


def _build_session(*, started_offset_hours: float, duration_minutes: float) -> SessionRecord:
    started_at = _now() - timedelta(hours=started_offset_hours)
    ended_at = started_at + timedelta(minutes=duration_minutes)
    return SessionRecord(
        session_id=f"sess-{started_offset_hours}",
        account_id="acc-1",
        started_at=started_at,
        ended_at=ended_at,
    )


class TestExtract:
    async def test_basic_extraction(self) -> None:
        rollup = _ClickhouseRollup(
            streams_24h=20.0,
            streams_7d=120.0,
            save_rate_24h=0.1,
            skip_rate_24h=0.3,
            queue_rate_24h=0.05,
            ip_diversity_24h=2.0,
            distinct_dsps_24h=1.0,
            captcha_encounters_24h=1.0,
            failed_streams_24h=2.0,
            partial_streams_24h=3.0,
            distinct_artists_24h=8.0,
            distinct_tracks_24h=15.0,
            night_streams_ratio_24h=0.2,
            rapid_skip_ratio_24h=0.1,
            country_changes_24h=1.0,
            user_agent_changes_7d=2.0,
            previous_quarantine_count_30d=0.0,
            fingerprint_age_days=45.0,
            geo_consistency_score=0.95,
            hour_of_day_consistency=0.7,
        )
        sessions = [
            _build_session(started_offset_hours=2.0, duration_minutes=30.0),
            _build_session(started_offset_hours=5.0, duration_minutes=45.0),
            _build_session(started_offset_hours=20.0, duration_minutes=60.0),
            _build_session(started_offset_hours=48.0, duration_minutes=90.0),
        ]
        extractor = FeatureExtractor(
            clickhouse_repo=FakeClickhouseRepo(rollup),
            session_repo=FakeSessionRepo(sessions),
            now_factory=_now,
        )
        vector = await extractor.extract("acc-1")

        assert vector.account_id == "acc-1"
        assert vector.streams_24h == 20.0
        assert vector.streams_7d == 120.0
        assert vector.sessions_24h == 3.0
        assert vector.avg_session_duration_minutes == (30.0 + 45.0 + 60.0) / 3.0
        assert vector.completion_rate_24h == (20.0 - 2.0 - 3.0) / 20.0
        assert vector.repeat_track_ratio_24h == 1.0 - 15.0 / 20.0

    async def test_no_sessions_in_window(self) -> None:
        rollup = _ClickhouseRollup(streams_24h=0.0)
        sessions = [
            _build_session(started_offset_hours=72.0, duration_minutes=10.0),
        ]
        extractor = FeatureExtractor(
            clickhouse_repo=FakeClickhouseRepo(rollup),
            session_repo=FakeSessionRepo(sessions),
            now_factory=_now,
        )
        vector = await extractor.extract("acc-1")
        assert vector.sessions_24h == 0.0
        assert vector.avg_session_duration_minutes == 0.0
        assert vector.completion_rate_24h == 0.0
        assert vector.repeat_track_ratio_24h == 0.0


class TestHelpers:
    def test_completion_rate_zero_streams(self) -> None:
        assert _completion_rate(_ClickhouseRollup(streams_24h=0.0)) == 0.0

    def test_completion_rate_normal(self) -> None:
        rollup = _ClickhouseRollup(
            streams_24h=10.0,
            failed_streams_24h=2.0,
            partial_streams_24h=1.0,
        )
        assert _completion_rate(rollup) == 0.7

    def test_repeat_track_ratio_no_streams(self) -> None:
        assert _repeat_track_ratio(_ClickhouseRollup(streams_24h=0.0)) == 0.0

    def test_repeat_track_ratio_no_repeats(self) -> None:
        rollup = _ClickhouseRollup(streams_24h=10.0, distinct_tracks_24h=10.0)
        assert _repeat_track_ratio(rollup) == 0.0

    def test_repeat_track_ratio_full_repeat(self) -> None:
        rollup = _ClickhouseRollup(streams_24h=10.0, distinct_tracks_24h=1.0)
        assert _repeat_track_ratio(rollup) == 0.9

    def test_repeat_track_ratio_clipped_when_distinct_exceeds_total(self) -> None:
        rollup = _ClickhouseRollup(streams_24h=5.0, distinct_tracks_24h=20.0)
        # Saturamos distinct a streams_24h: ratio = 1 - 5/5 = 0.0
        assert _repeat_track_ratio(rollup) == 0.0
