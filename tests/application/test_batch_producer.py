"""Tests del ``BatchProducer``.

Cubren:
- Concurrencia limitada por ``max_concurrency`` (semaforo).
- Aislamiento de fallos por brief (no abortan el batch).
- Budget guard: skip cuando el coste acumulado supera el cap.
- Recoleccion de spent_cents y agrupacion de resultados.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from streaming_bot.application.catalog_pipeline.batch_producer import BatchProducer
from streaming_bot.application.catalog_pipeline.produce_track_use_case import (
    ProducedTrack,
)
from streaming_bot.domain.catalog_pipeline.track_brief import TrackBrief
from streaming_bot.domain.value_objects import Country


def _brief(mood: str = "calm") -> TrackBrief:
    return TrackBrief(
        niche="lo-fi",
        mood=mood,
        bpm_range=(70, 80),
        duration_seconds=180,
        target_geos=(Country.US,),
    )


def _produced(track_id: str) -> ProducedTrack:
    # Sentinel barato: usamos MagicMocks tipados y valor fijo de track_id.
    song = MagicMock(name=f"song-{track_id}")
    raw = MagicMock(name=f"raw-{track_id}")
    metadata = MagicMock(name=f"metadata-{track_id}")
    return ProducedTrack(track_id=track_id, song=song, raw=raw, metadata=metadata)


def _build_producer(
    use_case: AsyncMock,
    *,
    max_concurrency: int = 2,
    cost_per_track_cents: float = 10.0,
    budget_cents_cap: float = 100.0,
) -> BatchProducer:
    return BatchProducer(
        use_case=use_case,
        max_concurrency=max_concurrency,
        cost_per_track_cents=cost_per_track_cents,
        budget_cents_cap=budget_cents_cap,
        logger=structlog.get_logger("test"),
    )


class TestBatchProducer:
    async def test_produces_all_within_budget(self) -> None:
        use_case = AsyncMock()
        use_case.execute.side_effect = lambda brief: _produced(f"id-{brief.mood}")
        producer = _build_producer(use_case)

        briefs = [_brief("a"), _brief("b"), _brief("c")]
        result = await producer.produce_batch(briefs)

        assert len(result.produced) == 3
        assert {p.track_id for p in result.produced} == {"id-a", "id-b", "id-c"}
        assert result.spent_cents == pytest.approx(30.0)
        assert not result.failures
        assert not result.skipped_over_budget

    async def test_skips_briefs_over_budget(self) -> None:
        use_case = AsyncMock()
        use_case.execute.side_effect = lambda brief: _produced(brief.mood)
        producer = _build_producer(
            use_case,
            cost_per_track_cents=20.0,
            budget_cents_cap=40.0,
        )

        briefs = [_brief(f"m{i}") for i in range(5)]
        result = await producer.produce_batch(briefs)

        assert len(result.produced) == 2
        assert len(result.skipped_over_budget) == 3
        assert result.spent_cents == pytest.approx(40.0)
        assert use_case.execute.await_count == 2

    async def test_failures_isolated_and_refund_budget(self) -> None:
        use_case = AsyncMock()

        def _executor(brief: TrackBrief) -> ProducedTrack:
            if brief.mood == "bad":
                raise RuntimeError("suno fail")
            return _produced(brief.mood)

        use_case.execute.side_effect = _executor
        producer = _build_producer(
            use_case,
            cost_per_track_cents=10.0,
            budget_cents_cap=30.0,
        )

        briefs = [_brief("ok-1"), _brief("bad"), _brief("ok-2")]
        result = await producer.produce_batch(briefs)

        assert len(result.produced) == 2
        assert {p.track_id for p in result.produced} == {"ok-1", "ok-2"}
        assert len(result.failures) == 1
        assert result.failures[0][0].mood == "bad"
        assert "suno fail" in result.failures[0][1]
        # Coste reembolsado: 2 exitosos x 10 cents.
        assert result.spent_cents == pytest.approx(20.0)

    async def test_respects_concurrency_limit(self) -> None:
        in_flight = 0
        peak = 0
        gate = asyncio.Event()

        async def _slow_execute(brief: TrackBrief) -> ProducedTrack:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await gate.wait()
            in_flight -= 1
            return _produced(brief.mood)

        use_case = AsyncMock()
        use_case.execute.side_effect = _slow_execute
        producer = _build_producer(
            use_case,
            max_concurrency=2,
            budget_cents_cap=1_000.0,
        )
        briefs = [_brief(f"m{i}") for i in range(6)]

        async def _release_after() -> None:
            await asyncio.sleep(0)
            gate.set()

        results, _ = await asyncio.gather(
            producer.produce_batch(briefs),
            _release_after(),
        )
        assert peak <= 2
        assert len(results.produced) == 6

    async def test_invalid_constructor_args_raise(self) -> None:
        use_case = AsyncMock()
        with pytest.raises(ValueError, match="max_concurrency"):
            _build_producer(use_case, max_concurrency=0)
        with pytest.raises(ValueError, match="cost_per_track_cents"):
            _build_producer(use_case, cost_per_track_cents=-1.0)
        with pytest.raises(ValueError, match="budget_cents_cap"):
            _build_producer(use_case, budget_cents_cap=-1.0)
