"""Tests del `SuperFanEmulationEngine`.

Las propiedades verificadas son:
1. Sesion total >= min_session_minutes (45min por defecto).
2. Target aparece 1-2 veces y al menos 1 vez como replay.
3. Filler ratio (otros artistas) >= 60% del tiempo de escucha.
4. Jitter por play en el rango [3, 15] segundos.
5. ValueError si followed_artists_pool esta vacio.
"""

from __future__ import annotations

import pytest

from streaming_bot.application.deezer import (
    SuperFanEmulationEngine,
    TrackCandidate,
)


def _target() -> TrackCandidate:
    return TrackCandidate(
        uri="deezer:track:1001",
        artist_uri="deezer:artist:42",
        duration_seconds=210,
    )


def _target_artist_pool() -> list[TrackCandidate]:
    return [
        TrackCandidate(
            uri=f"deezer:track:200{i}",
            artist_uri="deezer:artist:42",
            duration_seconds=180 + i * 5,
        )
        for i in range(8)
    ]


def _followed_pool() -> list[TrackCandidate]:
    return [
        TrackCandidate(
            uri=f"deezer:track:300{i}",
            artist_uri=f"deezer:artist:{100 + i}",
            duration_seconds=190 + i * 3,
        )
        for i in range(20)
    ]


class TestPlannedSessionConstraints:
    def test_session_meets_minimum_duration(self) -> None:
        engine = SuperFanEmulationEngine(rng_seed=7, min_session_minutes=45)
        plan = engine.plan_session(
            target_track=_target(),
            target_artist_pool=_target_artist_pool(),
            followed_artists_pool=_followed_pool(),
        )
        assert plan.total_seconds >= 45 * 60

    def test_target_appears_one_or_two_times(self) -> None:
        engine = SuperFanEmulationEngine(rng_seed=7)
        plan = engine.plan_session(
            target_track=_target(),
            target_artist_pool=_target_artist_pool(),
            followed_artists_pool=_followed_pool(),
        )
        assert 1 <= plan.target_play_count <= 2

    def test_target_uri_matches(self) -> None:
        target = _target()
        engine = SuperFanEmulationEngine(rng_seed=7)
        plan = engine.plan_session(
            target_track=target,
            target_artist_pool=_target_artist_pool(),
            followed_artists_pool=_followed_pool(),
        )
        assert plan.target_track_uri == target.uri
        target_plays = [p for p in plan.plays if p.is_target]
        assert all(p.track_uri == target.uri for p in target_plays)

    def test_filler_ratio_above_60_percent(self) -> None:
        engine = SuperFanEmulationEngine(rng_seed=7)
        plan = engine.plan_session(
            target_track=_target(),
            target_artist_pool=_target_artist_pool(),
            followed_artists_pool=_followed_pool(),
        )
        assert plan.filler_ratio >= 0.6

    def test_jitter_in_human_range(self) -> None:
        engine = SuperFanEmulationEngine(rng_seed=7)
        plan = engine.plan_session(
            target_track=_target(),
            target_artist_pool=_target_artist_pool(),
            followed_artists_pool=_followed_pool(),
        )
        for play in plan.plays:
            assert 3 <= play.pre_jitter_seconds <= 15

    def test_listen_seconds_at_least_35(self) -> None:
        """Cada play >= 35s para contar como stream valido en Deezer."""
        engine = SuperFanEmulationEngine(rng_seed=42)
        plan = engine.plan_session(
            target_track=_target(),
            target_artist_pool=_target_artist_pool(),
            followed_artists_pool=_followed_pool(),
        )
        for play in plan.plays:
            assert play.listen_seconds >= 35

    def test_replay_flag_only_set_on_repeated_target(self) -> None:
        engine = SuperFanEmulationEngine(rng_seed=7)
        plan = engine.plan_session(
            target_track=_target(),
            target_artist_pool=_target_artist_pool(),
            followed_artists_pool=_followed_pool(),
        )
        target_plays = [p for p in plan.plays if p.is_target]
        # Solo el segundo (si existe) puede ser replay.
        assert target_plays[0].is_replay is False
        if len(target_plays) > 1:
            assert target_plays[1].is_replay is True


class TestPlannedSessionDeterminism:
    def test_same_seed_yields_same_plan(self) -> None:
        engine_a = SuperFanEmulationEngine(rng_seed=99)
        engine_b = SuperFanEmulationEngine(rng_seed=99)
        plan_a = engine_a.plan_session(
            target_track=_target(),
            target_artist_pool=_target_artist_pool(),
            followed_artists_pool=_followed_pool(),
        )
        plan_b = engine_b.plan_session(
            target_track=_target(),
            target_artist_pool=_target_artist_pool(),
            followed_artists_pool=_followed_pool(),
        )
        assert plan_a == plan_b


class TestPlannedSessionGuardRails:
    def test_empty_followed_pool_raises(self) -> None:
        engine = SuperFanEmulationEngine(rng_seed=1)
        with pytest.raises(ValueError, match="followed_artists_pool"):
            engine.plan_session(
                target_track=_target(),
                target_artist_pool=_target_artist_pool(),
                followed_artists_pool=[],
            )

    def test_invalid_min_session_raises(self) -> None:
        with pytest.raises(ValueError, match="min_session_minutes"):
            SuperFanEmulationEngine(rng_seed=1, min_session_minutes=0)

    def test_invalid_filler_ratio_raises(self) -> None:
        with pytest.raises(ValueError, match="min_filler_ratio"):
            SuperFanEmulationEngine(rng_seed=1, min_filler_ratio=1.5)

    def test_short_track_rejected(self) -> None:
        with pytest.raises(ValueError, match="duration_seconds"):
            TrackCandidate(
                uri="deezer:track:zz",
                artist_uri="deezer:artist:1",
                duration_seconds=20,
            )

    def test_session_works_without_target_artist_pool(self) -> None:
        engine = SuperFanEmulationEngine(rng_seed=3)
        plan = engine.plan_session(
            target_track=_target(),
            target_artist_pool=(),
            followed_artists_pool=_followed_pool(),
        )
        assert plan.target_play_count >= 1
        assert plan.total_seconds >= 45 * 60
