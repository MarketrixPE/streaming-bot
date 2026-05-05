"""Tests del DispatcherRouter.

Verifica:
- Construccion: rechaza adapter cuyo distributor no coincide con la clave.
- dispatch en paralelo: invoca cada adapter; un fallo NO aborta los demas.
- Llamadas con distribuidor no cableado fallan.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from streaming_bot.domain.distribution.distributor_id import DistributorId
from streaming_bot.domain.distribution.release import (
    Release,
    ReleaseStatus,
    ReleaseSubmission,
    TrackRef,
)
from streaming_bot.domain.ports.distributor_dispatcher import DistributorAPIError
from streaming_bot.infrastructure.distributors.dispatcher_router import (
    DispatcherRouter,
)


def _release(distributor: DistributorId, *, artist_name: str = "Test Artist") -> Release:
    track = TrackRef(
        track_id="track-1",
        title="Demo",
        artist_name=artist_name,
        audio_path=Path("/tmp/track.wav"),
        isrc="USAT22612345",
        duration_seconds=210,
    )
    return Release.new(
        tracks=(track,),
        artist_name=artist_name,
        label_name="Worldwide Hits",
        distributor=distributor,
        release_date=date(2026, 5, 10),
    )


def _adapter(distributor: DistributorId) -> AsyncMock:
    """Construye un AsyncMock que cumple IDistributorDispatcher."""
    adapter = AsyncMock()
    adapter.distributor = distributor
    return adapter


class TestConstructor:
    def test_rejects_empty_adapters(self) -> None:
        with pytest.raises(ValueError, match="al menos un adapter"):
            DispatcherRouter(adapters={})

    def test_rejects_mismatched_adapter_distributor(self) -> None:
        adapter = _adapter(DistributorId.ROUTENOTE)
        with pytest.raises(ValueError, match="no coincide"):
            DispatcherRouter(adapters={DistributorId.DISTROKID: adapter})

    def test_available_distributors_returns_keys(self) -> None:
        router = DispatcherRouter(
            adapters={
                DistributorId.DISTROKID: _adapter(DistributorId.DISTROKID),
                DistributorId.ROUTENOTE: _adapter(DistributorId.ROUTENOTE),
            },
        )
        assert router.available_distributors == frozenset(
            {DistributorId.DISTROKID, DistributorId.ROUTENOTE},
        )


class TestDispatch:
    async def test_dispatch_calls_each_adapter_in_parallel(self) -> None:
        distrokid = _adapter(DistributorId.DISTROKID)
        routenote = _adapter(DistributorId.ROUTENOTE)

        events: list[str] = []

        async def _slow_distrokid(release: Release) -> ReleaseSubmission:
            events.append("dk-start")
            await asyncio.sleep(0.05)
            events.append("dk-end")
            return ReleaseSubmission(
                submission_id="dk-1",
                distributor=DistributorId.DISTROKID,
                release_id=release.release_id,
                submitted_at=datetime.now(UTC),
                status=ReleaseStatus.SUBMITTED,
            )

        async def _fast_routenote(release: Release) -> ReleaseSubmission:
            events.append("rn-start")
            events.append("rn-end")
            return ReleaseSubmission(
                submission_id="rn-1",
                distributor=DistributorId.ROUTENOTE,
                release_id=release.release_id,
                submitted_at=datetime.now(UTC),
                status=ReleaseStatus.SUBMITTED,
            )

        distrokid.submit_release.side_effect = _slow_distrokid
        routenote.submit_release.side_effect = _fast_routenote

        router = DispatcherRouter(
            adapters={
                DistributorId.DISTROKID: distrokid,
                DistributorId.ROUTENOTE: routenote,
            },
        )

        releases = {
            DistributorId.DISTROKID: _release(DistributorId.DISTROKID),
            DistributorId.ROUTENOTE: _release(DistributorId.ROUTENOTE),
        }

        results = await router.dispatch(releases)

        assert isinstance(results[DistributorId.DISTROKID], ReleaseSubmission)
        assert isinstance(results[DistributorId.ROUTENOTE], ReleaseSubmission)
        # Paralelismo: routenote arranca antes de que distrokid termine.
        assert events.index("rn-start") < events.index("dk-end")

    async def test_one_adapter_failure_does_not_abort_others(self) -> None:
        distrokid = _adapter(DistributorId.DISTROKID)
        routenote = _adapter(DistributorId.ROUTENOTE)

        distrokid.submit_release.side_effect = DistributorAPIError("selector roto")

        async def _ok(release: Release) -> ReleaseSubmission:
            return ReleaseSubmission(
                submission_id="rn-OK",
                distributor=DistributorId.ROUTENOTE,
                release_id=release.release_id,
                submitted_at=datetime.now(UTC),
                status=ReleaseStatus.SUBMITTED,
            )

        routenote.submit_release.side_effect = _ok

        router = DispatcherRouter(
            adapters={
                DistributorId.DISTROKID: distrokid,
                DistributorId.ROUTENOTE: routenote,
            },
        )

        releases = {
            DistributorId.DISTROKID: _release(DistributorId.DISTROKID),
            DistributorId.ROUTENOTE: _release(DistributorId.ROUTENOTE),
        }

        results = await router.dispatch(releases)

        assert isinstance(results[DistributorId.DISTROKID], DistributorAPIError)
        assert isinstance(results[DistributorId.ROUTENOTE], ReleaseSubmission)

    async def test_unknown_distributor_in_payload_raises(self) -> None:
        adapter = _adapter(DistributorId.ROUTENOTE)
        router = DispatcherRouter(adapters={DistributorId.ROUTENOTE: adapter})
        releases = {
            DistributorId.DISTROKID: _release(DistributorId.DISTROKID),
        }
        with pytest.raises(ValueError, match="sin adapter cableado"):
            await router.dispatch(releases)

    async def test_empty_payload_returns_empty(self) -> None:
        adapter = _adapter(DistributorId.ROUTENOTE)
        router = DispatcherRouter(adapters={DistributorId.ROUTENOTE: adapter})
        results = await router.dispatch({})
        assert results == {}
