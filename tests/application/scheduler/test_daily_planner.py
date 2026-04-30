"""Tests del DailyPlanner: respeto de tier, ceiling y exclusiones."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime

import pytest
import structlog

from streaming_bot.application.scheduler.daily_planner import (
    DailyPlanner,
    SongDailyTarget,
)
from streaming_bot.domain.ramp_up import TierRampUp
from streaming_bot.domain.song import (
    Distributor,
    Song,
    SongMetadata,
    SongRole,
    SongTier,
)
from streaming_bot.domain.value_objects import Country


@pytest.fixture(autouse=True)
def _seed_random() -> None:
    """RampUpPolicy usa random global para jitter; semilla para determinismo."""
    random.seed(0)


def _build_song(
    *,
    uri: str = "spotify:track:t1",
    tier: SongTier = SongTier.MID,
    role: SongRole = SongRole.TARGET,
    is_active: bool = True,
    spike_oct2025_flag: bool = False,
    baseline: float = 100.0,
    target_per_day: int = 200,
    current_today: int = 0,
) -> Song:
    return Song(
        spotify_uri=uri,
        title=f"title-{uri}",
        artist_name="artist",
        artist_uri="spotify:artist:a1",
        role=role,
        metadata=SongMetadata(duration_seconds=180),
        distributor=Distributor.DISTROKID,
        baseline_streams_per_day=baseline,
        target_streams_per_day=target_per_day,
        current_streams_today=current_today,
        is_active=is_active,
        tier=tier,
        spike_oct2025_flag=spike_oct2025_flag,
    )


def _make_planner(program_start: date | None = None) -> DailyPlanner:
    return DailyPlanner(
        program_start=program_start or date(2026, 4, 1),
        tier_policy=TierRampUp.conservative_pilot(),
        logger=structlog.get_logger("test"),
    )


class TestDailyPlanner:
    def test_excludes_flagged_tier(self) -> None:
        planner = _make_planner()
        songs = [
            _build_song(uri="spotify:track:flagged", tier=SongTier.FLAGGED),
            _build_song(uri="spotify:track:mid", tier=SongTier.MID),
        ]
        plan = planner.plan_for_today(songs, datetime(2026, 5, 1, tzinfo=UTC))
        ids = {p.song_id for p in plan}
        assert "spotify:track:flagged" not in ids
        assert "spotify:track:mid" in ids

    def test_excludes_spike_oct2025_flag(self) -> None:
        planner = _make_planner()
        songs = [
            _build_song(uri="spotify:track:spike", spike_oct2025_flag=True),
            _build_song(uri="spotify:track:clean"),
        ]
        plan = planner.plan_for_today(songs, datetime(2026, 5, 1, tzinfo=UTC))
        ids = {p.song_id for p in plan}
        assert "spotify:track:spike" not in ids
        assert "spotify:track:clean" in ids

    def test_excludes_hot_and_rising(self) -> None:
        planner = _make_planner()
        songs = [
            _build_song(uri="spotify:track:hot", tier=SongTier.HOT),
            _build_song(uri="spotify:track:rising", tier=SongTier.RISING),
            _build_song(uri="spotify:track:mid", tier=SongTier.MID),
        ]
        plan = planner.plan_for_today(songs, datetime(2026, 5, 1, tzinfo=UTC))
        ids = {p.song_id for p in plan}
        assert "spotify:track:hot" not in ids
        assert "spotify:track:rising" not in ids
        assert "spotify:track:mid" in ids

    def test_excludes_inactive(self) -> None:
        planner = _make_planner()
        songs = [
            _build_song(uri="spotify:track:off", is_active=False),
            _build_song(uri="spotify:track:on"),
        ]
        plan = planner.plan_for_today(songs, datetime(2026, 5, 1, tzinfo=UTC))
        ids = {p.song_id for p in plan}
        assert "spotify:track:off" not in ids

    def test_excludes_non_target_role(self) -> None:
        planner = _make_planner()
        songs = [
            _build_song(uri="spotify:track:cam", role=SongRole.CAMOUFLAGE),
            _build_song(uri="spotify:track:disc", role=SongRole.DISCOVERY),
            _build_song(uri="spotify:track:tgt"),
        ]
        plan = planner.plan_for_today(songs, datetime(2026, 5, 1, tzinfo=UTC))
        ids = {p.song_id for p in plan}
        assert ids == {"spotify:track:tgt"}

    def test_target_capped_by_safe_ceiling(self) -> None:
        """Si el ramp-up calcula > ceiling, el target debe quedarse en ceiling."""
        planner = _make_planner(program_start=date(2026, 1, 1))
        # baseline alto -> ceiling = baseline*1.5 = 15 (pero capped por target)
        song = _build_song(
            tier=SongTier.MID,
            baseline=10.0,
            target_per_day=15,
        )
        plan = planner.plan_for_today([song], datetime(2026, 5, 1, tzinfo=UTC))
        assert plan
        assert plan[0].streams_target <= song.safe_ceiling_today()

    def test_zombie_with_low_baseline_uses_floor_ceiling(self) -> None:
        """Zombies con baseline ~0 usan el ceiling de fallback (20% target)."""
        planner = _make_planner(program_start=date(2026, 1, 1))
        song = _build_song(
            tier=SongTier.ZOMBIE,
            baseline=0.0,
            target_per_day=100,
        )
        plan = planner.plan_for_today([song], datetime(2026, 5, 1, tzinfo=UTC))
        assert plan
        # safe_ceiling_today para baseline<1 = max(target*0.20, 5) = 20
        assert plan[0].streams_target <= 20

    def test_allowed_countries_phase1_latam(self) -> None:
        """En los primeros 90 dias el plan debe usar phase-1-latam-only."""
        planner = _make_planner(program_start=date(2026, 4, 1))
        song = _build_song(tier=SongTier.MID)
        plan = planner.plan_for_today([song], datetime(2026, 4, 15, tzinfo=UTC))
        assert plan
        # phase-1 NO incluye GB ni CH
        countries = plan[0].allowed_countries
        assert Country.GB not in countries
        assert Country.CH not in countries
        assert Country.PE in countries

    def test_days_since_start_clamped_at_zero(self) -> None:
        """Si la fecha es anterior al program_start, days_since_start == 0."""
        planner = _make_planner(program_start=date(2026, 6, 1))
        song = _build_song(tier=SongTier.MID, baseline=50, target_per_day=80)
        plan = planner.plan_for_today([song], datetime(2026, 5, 1, tzinfo=UTC))
        # day_offset negativo -> sigmoid evalua en negativo pero policy
        # devuelve 0 si day_offset<0; entonces el plan podria estar vacio.
        # Lo importante: si hay plan, days_since_start es 0.
        for entry in plan:
            assert entry.days_since_start == 0

    def test_returns_list_of_song_daily_target(self) -> None:
        planner = _make_planner()
        plan = planner.plan_for_today([_build_song()], datetime(2026, 5, 15, tzinfo=UTC))
        assert all(isinstance(p, SongDailyTarget) for p in plan)

    def test_empty_catalog_returns_empty_plan(self) -> None:
        planner = _make_planner()
        plan = planner.plan_for_today([], datetime(2026, 5, 1, tzinfo=UTC))
        assert plan == []

    def test_returns_immutable_targets(self) -> None:
        planner = _make_planner()
        plan = planner.plan_for_today([_build_song()], datetime(2026, 5, 15, tzinfo=UTC))
        if plan:
            with pytest.raises((AttributeError, Exception)):
                plan[0].streams_target = 9999  # type: ignore[misc]
