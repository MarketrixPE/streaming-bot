"""Tests unitarios de `SuperFanProfile` y `DeezerListenerHistory`."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from streaming_bot.domain.deezer import (
    DeezerListenerHistory,
    SuperFanProfile,
)


class TestSuperFanProfileDefaults:
    def test_defaults_match_acps_thresholds(self) -> None:
        profile = SuperFanProfile()
        assert profile.artists_followed_min == 50
        assert profile.avg_session_minutes_min == 45.0
        assert profile.replay_rate_min == 0.3
        assert profile.distinct_tracks_30d_min == 200
        assert profile.distinct_albums_30d_min == 30

    def test_strict_factory_returns_acps_thresholds(self) -> None:
        strict = SuperFanProfile.strict()
        assert strict == SuperFanProfile()

    def test_lenient_factory_lowers_thresholds(self) -> None:
        lenient = SuperFanProfile.lenient()
        strict = SuperFanProfile.strict()
        assert lenient.artists_followed_min < strict.artists_followed_min
        assert lenient.avg_session_minutes_min < strict.avg_session_minutes_min
        assert lenient.replay_rate_min < strict.replay_rate_min


class TestSuperFanProfileValidation:
    def test_negative_artists_raises(self) -> None:
        with pytest.raises(ValueError, match="artists_followed_min"):
            SuperFanProfile(artists_followed_min=-1)

    def test_negative_session_minutes_raises(self) -> None:
        with pytest.raises(ValueError, match="avg_session_minutes_min"):
            SuperFanProfile(avg_session_minutes_min=-0.1)

    def test_replay_rate_zero_is_invalid(self) -> None:
        with pytest.raises(ValueError, match="replay_rate_min"):
            SuperFanProfile(replay_rate_min=0.0)

    def test_replay_rate_above_one_is_invalid(self) -> None:
        with pytest.raises(ValueError, match="replay_rate_min"):
            SuperFanProfile(replay_rate_min=1.1)


class TestDeezerListenerHistory:
    def test_default_history_is_empty(self) -> None:
        h = DeezerListenerHistory(account_id="acct-1")
        assert h.artists_followed_count == 0
        assert h.avg_session_minutes_30d == 0.0
        assert h.replay_rate == 0.0
        assert h.distinct_tracks_30d == 0
        assert h.distinct_albums_30d == 0
        assert h.last_session_at is None

    def test_invalid_replay_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="replay_rate"):
            DeezerListenerHistory(account_id="x", replay_rate=1.5)

    def test_negative_distinct_tracks_raises(self) -> None:
        with pytest.raises(ValueError, match="distinct_tracks_30d"):
            DeezerListenerHistory(account_id="x", distinct_tracks_30d=-1)

    def test_matches_returns_true_when_meets_all_thresholds(self) -> None:
        profile = SuperFanProfile()
        history = DeezerListenerHistory(
            account_id="acct-1",
            artists_followed=tuple(f"artist-{i}" for i in range(60)),
            avg_session_minutes_30d=50.0,
            replay_rate=0.4,
            distinct_tracks_30d=300,
            distinct_albums_30d=40,
            last_session_at=datetime.now(UTC),
        )
        assert history.matches(profile) is True

    def test_matches_returns_false_when_one_threshold_fails(self) -> None:
        profile = SuperFanProfile()
        history = DeezerListenerHistory(
            account_id="acct-1",
            artists_followed=tuple(f"artist-{i}" for i in range(60)),
            avg_session_minutes_30d=50.0,
            replay_rate=0.4,
            distinct_tracks_30d=199,  # un track por debajo del umbral
            distinct_albums_30d=40,
        )
        assert history.matches(profile) is False

    def test_gap_against_returns_signed_deltas(self) -> None:
        profile = SuperFanProfile()
        history = DeezerListenerHistory(
            account_id="acct-1",
            artists_followed=tuple(f"artist-{i}" for i in range(30)),
            avg_session_minutes_30d=20.0,
            replay_rate=0.2,
            distinct_tracks_30d=150,
            distinct_albums_30d=10,
        )
        gap = history.gap_against(profile)
        assert gap.artists_followed_missing == 20
        assert gap.avg_session_minutes_missing == 25.0
        assert pytest.approx(gap.replay_rate_missing, abs=1e-9) == 0.1
        assert gap.distinct_tracks_30d_missing == 50
        assert gap.distinct_albums_30d_missing == 20
        assert gap.is_zero is False

    def test_gap_zero_when_history_exceeds_thresholds(self) -> None:
        profile = SuperFanProfile()
        history = DeezerListenerHistory(
            account_id="acct-1",
            artists_followed=tuple(f"a-{i}" for i in range(100)),
            avg_session_minutes_30d=120.0,
            replay_rate=0.9,
            distinct_tracks_30d=500,
            distinct_albums_30d=100,
        )
        assert history.gap_against(profile).is_zero is True
