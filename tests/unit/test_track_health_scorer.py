"""Tests del TrackHealthScorer + adapter ClickHouse (track health)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest

from streaming_bot.application.routing import policy as policy_module
from streaming_bot.application.routing.policy import RoutingPolicy
from streaming_bot.application.routing.track_health_scorer import TrackHealthScorer
from streaming_bot.domain.history import StreamHistory, StreamOutcome
from streaming_bot.domain.routing.tier import Tier
from streaming_bot.domain.routing.track_health import TrackHealthScore
from streaming_bot.domain.song import Song, SongMetadata, SongRole
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.routing.clickhouse_track_health_repo import (
    ClickhouseTrackHealthRepository,
)

SONG_URI = "spotify:track:abc"
NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


def _song(release: date | None = date(2026, 1, 1)) -> Song:
    return Song(
        spotify_uri=SONG_URI,
        title="t",
        artist_name="x",
        artist_uri="spotify:artist:y",
        role=SongRole.TARGET,
        metadata=SongMetadata(duration_seconds=180, release_date=release),
    )


def _hist(
    *,
    occurred_at: datetime,
    outcome: StreamOutcome,
    song_uri: str = SONG_URI,
) -> StreamHistory:
    return StreamHistory(
        history_id="h",
        account_id="a1",
        song_uri=song_uri,
        artist_uri="spotify:artist:y",
        occurred_at=occurred_at,
        duration_listened_seconds=40 if outcome == StreamOutcome.COUNTED else 0,
        outcome=outcome,
    )


class TestAgeDays:
    def test_age_from_release_date(self) -> None:
        scorer = TrackHealthScorer()
        score = scorer.score(
            song=_song(release=date(2026, 4, 4)),
            histories=[],
            saves_count=0,
            as_of=NOW,
        )
        assert score.age_days == 30

    def test_no_release_date_returns_zero(self) -> None:
        scorer = TrackHealthScorer()
        score = scorer.score(
            song=_song(release=None),
            histories=[],
            saves_count=0,
            as_of=NOW,
        )
        assert score.age_days == 0

    def test_future_release_clamped_to_zero(self) -> None:
        scorer = TrackHealthScorer()
        score = scorer.score(
            song=_song(release=date(2026, 6, 1)),
            histories=[],
            saves_count=0,
            as_of=NOW,
        )
        assert score.age_days == 0


class TestPlaysAndRates:
    def test_plays_30d_counts_only_counted_within_window(self) -> None:
        scorer = TrackHealthScorer()
        histories = [
            _hist(occurred_at=NOW - timedelta(days=1), outcome=StreamOutcome.COUNTED),
            _hist(occurred_at=NOW - timedelta(days=5), outcome=StreamOutcome.COUNTED),
            # Fuera de ventana 30d.
            _hist(occurred_at=NOW - timedelta(days=40), outcome=StreamOutcome.COUNTED),
            # Otros outcomes no cuentan.
            _hist(occurred_at=NOW - timedelta(days=2), outcome=StreamOutcome.PARTIAL),
            _hist(occurred_at=NOW - timedelta(days=2), outcome=StreamOutcome.SKIPPED),
        ]
        score = scorer.score(
            song=_song(),
            histories=histories,
            saves_count=0,
            as_of=NOW,
        )
        assert score.plays_30d == 2

    def test_skip_rate_excludes_pending(self) -> None:
        scorer = TrackHealthScorer()
        histories = [
            _hist(occurred_at=NOW - timedelta(days=1), outcome=StreamOutcome.COUNTED),
            _hist(occurred_at=NOW - timedelta(days=1), outcome=StreamOutcome.COUNTED),
            _hist(occurred_at=NOW - timedelta(days=1), outcome=StreamOutcome.SKIPPED),
            # PENDING ignorado.
            _hist(occurred_at=NOW - timedelta(days=1), outcome=StreamOutcome.PENDING),
        ]
        score = scorer.score(
            song=_song(),
            histories=histories,
            saves_count=0,
            as_of=NOW,
        )
        assert score.skip_rate == pytest.approx(1 / 3)

    def test_skip_rate_zero_when_no_attempts(self) -> None:
        scorer = TrackHealthScorer()
        score = scorer.score(
            song=_song(),
            histories=[],
            saves_count=0,
            as_of=NOW,
        )
        assert score.skip_rate == 0.0
        assert score.plays_30d == 0

    def test_save_rate_relative_to_plays(self) -> None:
        scorer = TrackHealthScorer()
        histories = [
            _hist(occurred_at=NOW - timedelta(days=1), outcome=StreamOutcome.COUNTED)
            for _ in range(100)
        ]
        score = scorer.score(
            song=_song(),
            histories=histories,
            saves_count=5,
            as_of=NOW,
        )
        assert score.save_rate == pytest.approx(0.05)

    def test_save_rate_truncated_to_one(self) -> None:
        scorer = TrackHealthScorer()
        histories = [
            _hist(occurred_at=NOW - timedelta(days=1), outcome=StreamOutcome.COUNTED)
            for _ in range(10)
        ]
        score = scorer.score(
            song=_song(),
            histories=histories,
            saves_count=50,
            as_of=NOW,
        )
        assert score.save_rate == 1.0

    def test_save_rate_zero_when_no_plays(self) -> None:
        scorer = TrackHealthScorer()
        score = scorer.score(
            song=_song(),
            histories=[],
            saves_count=10,
            as_of=NOW,
        )
        assert score.save_rate == 0.0

    def test_negative_saves_rejected(self) -> None:
        scorer = TrackHealthScorer()
        with pytest.raises(ValueError, match="saves_count"):
            scorer.score(
                song=_song(),
                histories=[],
                saves_count=-1,
                as_of=NOW,
            )

    def test_filters_other_song_uris(self) -> None:
        scorer = TrackHealthScorer()
        histories = [
            _hist(occurred_at=NOW - timedelta(days=1), outcome=StreamOutcome.COUNTED),
            _hist(
                occurred_at=NOW - timedelta(days=1),
                outcome=StreamOutcome.COUNTED,
                song_uri="spotify:track:OTHER",
            ),
        ]
        score = scorer.score(
            song=_song(),
            histories=histories,
            saves_count=0,
            as_of=NOW,
        )
        assert score.plays_30d == 1


class TestSaturation:
    def test_no_streams_returns_zero(self) -> None:
        scorer = TrackHealthScorer()
        score = scorer.score(
            song=_song(),
            histories=[],
            saves_count=0,
            streams_24h_by_country={},
            as_of=NOW,
        )
        assert score.saturation_score == 0.0

    def test_max_across_countries(self) -> None:
        scorer = TrackHealthScorer()
        score = scorer.score(
            song=_song(),
            histories=[],
            saves_count=0,
            streams_24h_by_country={
                Country.US: 750,  # 750/1500 = 0.5 (TIER_1)
                Country.MX: 3000,  # 3000/3500 ~ 0.857 (TIER_2)
                Country.BR: 4500,  # 4500/9000 = 0.5 (TIER_3)
            },
            as_of=NOW,
        )
        assert score.saturation_score == pytest.approx(3000 / 3500)

    def test_saturation_can_exceed_one(self) -> None:
        scorer = TrackHealthScorer()
        score = scorer.score(
            song=_song(),
            histories=[],
            saves_count=0,
            streams_24h_by_country={Country.US: 3000},  # 3000/1500 = 2.0
            as_of=NOW,
        )
        assert score.saturation_score == pytest.approx(2.0)

    def test_unknown_country_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Forzamos un mapping reducido para que MX caiga fuera de los tiers.
        monkeypatch.setattr(
            policy_module,
            "TIER_TO_COUNTRIES",
            {Tier.TIER_1: frozenset({Country.US})},
        )
        scorer = TrackHealthScorer(policy=RoutingPolicy())
        score = scorer.score(
            song=_song(),
            histories=[],
            saves_count=0,
            streams_24h_by_country={
                Country.MX: 9999,  # ahora MX no esta mapeado
                Country.US: 600,  # 600 / 1500 = 0.4
            },
            as_of=NOW,
        )
        assert score.saturation_score == pytest.approx(0.4)


class TestEndToEnd:
    def test_full_snapshot_shape(self) -> None:
        scorer = TrackHealthScorer()
        histories = [
            _hist(occurred_at=NOW - timedelta(days=2), outcome=StreamOutcome.COUNTED),
            _hist(occurred_at=NOW - timedelta(days=2), outcome=StreamOutcome.COUNTED),
            _hist(occurred_at=NOW - timedelta(days=2), outcome=StreamOutcome.SKIPPED),
        ]
        snapshot = scorer.score(
            song=_song(release=date(2026, 4, 27)),
            histories=histories,
            saves_count=1,
            streams_24h_by_country={Country.US: 600},
            as_of=NOW,
        )
        assert isinstance(snapshot, TrackHealthScore)
        assert snapshot.age_days == 7
        assert snapshot.plays_30d == 2
        assert snapshot.skip_rate == pytest.approx(1 / 3)
        assert snapshot.save_rate == pytest.approx(0.5)
        assert snapshot.saturation_score == pytest.approx(0.4)
        assert snapshot.computed_at == NOW

    def test_default_policy_when_none_provided(self) -> None:
        scorer = TrackHealthScorer(policy=None)
        snapshot = scorer.score(
            song=_song(),
            histories=[],
            saves_count=0,
            as_of=NOW,
        )
        assert snapshot.plays_30d == 0


class TestTrackHealthScoreInvariants:
    def test_negative_age_rejected(self) -> None:
        with pytest.raises(ValueError, match="age_days"):
            TrackHealthScore(
                age_days=-1,
                plays_30d=0,
                save_rate=0.0,
                skip_rate=0.0,
                saturation_score=0.0,
                computed_at=NOW,
            )

    def test_negative_plays_rejected(self) -> None:
        with pytest.raises(ValueError, match="plays_30d"):
            TrackHealthScore(
                age_days=0,
                plays_30d=-5,
                save_rate=0.0,
                skip_rate=0.0,
                saturation_score=0.0,
                computed_at=NOW,
            )

    def test_save_rate_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="save_rate"):
            TrackHealthScore(
                age_days=0,
                plays_30d=0,
                save_rate=1.5,
                skip_rate=0.0,
                saturation_score=0.0,
                computed_at=NOW,
            )

    def test_skip_rate_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="skip_rate"):
            TrackHealthScore(
                age_days=0,
                plays_30d=0,
                save_rate=0.0,
                skip_rate=-0.1,
                saturation_score=0.0,
                computed_at=NOW,
            )

    def test_negative_saturation_rejected(self) -> None:
        with pytest.raises(ValueError, match="saturation_score"):
            TrackHealthScore(
                age_days=0,
                plays_30d=0,
                save_rate=0.0,
                skip_rate=0.0,
                saturation_score=-0.5,
                computed_at=NOW,
            )


# ---------------------------------------------------------------------------
# Adapter ClickHouse: tests con httpx MockTransport (sin red, sin docker).
# ---------------------------------------------------------------------------


def _build_ch_client(
    response_by_query: dict[str, dict[str, Any]],
) -> httpx.AsyncClient:
    """Construye un AsyncClient cuyo MockTransport mapea SQL -> JSON.

    Matchea cada query por una substring discriminante (FROM, GROUP BY o
    WHERE behavior) que permite saber a que rama responder.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params.get("query", "")
        for fragment, payload in response_by_query.items():
            if fragment in query:
                return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"data": []})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestClickhouseTrackHealthRepository:
    async def test_get_returns_none_when_no_events(self) -> None:
        client = _build_ch_client({"FROM events.stream_events": {"data": []}})
        try:
            repo = ClickhouseTrackHealthRepository(client=client)
            score = await repo.get("spotify:track:abc", as_of=NOW)
            assert score is None
        finally:
            await client.aclose()

    async def test_get_reconstructs_score_from_rollups(self) -> None:
        # Order matters: dicts preservan insercion y el handler matchea
        # el primer fragmento contenido en la query.
        responses = {
            "GROUP BY proxy_country": {
                "data": [
                    {"country": "US", "streams": 600},
                    {"country": "MX", "streams": 1200},
                    {"country": "ZZ", "streams": 999},  # ignorado: no en enum
                ]
            },
            "behavior_events": {"data": [{"saves": 4}]},
            "AS attempts": {
                "data": [
                    {
                        "plays": 100,
                        "skipped": 10,
                        "attempts": 110,
                    }
                ]
            },
        }
        client = _build_ch_client(responses)
        try:
            repo = ClickhouseTrackHealthRepository(client=client)
            score = await repo.get("spotify:track:abc", as_of=NOW)
            assert score is not None
            assert score.plays_30d == 100
            assert score.skip_rate == pytest.approx(10 / 110)
            assert score.save_rate == pytest.approx(4 / 100)
            # MX (TIER_2): 1200 / 3500 = 0.342857...; US (TIER_1): 600/1500=0.4.
            assert score.saturation_score == pytest.approx(0.4)
            assert score.age_days == 0  # repo no conoce release_date
            assert score.computed_at == NOW
        finally:
            await client.aclose()

    async def test_streams_24h_by_country_drops_invalid_codes(self) -> None:
        responses = {
            "GROUP BY proxy_country": {
                "data": [
                    {"country": "US", "streams": 7},
                    {"country": "ZZ", "streams": 999},
                    {"country": "BR", "streams": 3},
                ]
            }
        }
        client = _build_ch_client(responses)
        try:
            repo = ClickhouseTrackHealthRepository(client=client)
            result = await repo.streams_24h_by_country(
                "spotify:track:abc",
                as_of=NOW,
            )
            assert result == {Country.US: 7, Country.BR: 3}
        finally:
            await client.aclose()

    async def test_upsert_is_no_op(self) -> None:
        client = _build_ch_client({})
        try:
            repo = ClickhouseTrackHealthRepository(client=client)
            score = TrackHealthScore(
                age_days=0,
                plays_30d=0,
                save_rate=0.0,
                skip_rate=0.0,
                saturation_score=0.0,
                computed_at=NOW,
            )
            await repo.upsert("spotify:track:abc", score)  # no debe lanzar
        finally:
            await client.aclose()

    async def test_compute_saturation_skips_unknown_country(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            policy_module,
            "TIER_TO_COUNTRIES",
            {Tier.TIER_1: frozenset({Country.US})},
        )
        client = _build_ch_client({})
        try:
            repo = ClickhouseTrackHealthRepository(client=client)
            sat = repo._compute_saturation({Country.MX: 9999, Country.US: 750})
            # Solo US cuenta (750/1500=0.5); MX no tiene tier en el mapping reducido.
            assert sat == pytest.approx(0.5)
        finally:
            await client.aclose()

    async def test_compute_saturation_empty_returns_zero(self) -> None:
        client = _build_ch_client({})
        try:
            repo = ClickhouseTrackHealthRepository(client=client)
            assert repo._compute_saturation({}) == 0.0
        finally:
            await client.aclose()

    async def test_get_uses_attempts_zero_with_saves_yields_score(self) -> None:
        # Sin streams pero con saves -> aun consideramos que hay actividad.
        responses = {
            "GROUP BY proxy_country": {"data": []},
            "behavior_events": {"data": [{"saves": 5}]},
            "AS attempts": {"data": [{"plays": 0, "skipped": 0, "attempts": 0}]},
        }
        client = _build_ch_client(responses)
        try:
            repo = ClickhouseTrackHealthRepository(client=client)
            score = await repo.get("spotify:track:abc", as_of=NOW)
            assert score is not None
            assert score.plays_30d == 0
            assert score.skip_rate == 0.0
            assert score.save_rate == 0.0  # plays_30d = 0 -> save_rate = 0
        finally:
            await client.aclose()
