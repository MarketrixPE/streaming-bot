"""Tests del MultiDistributorDispatchUseCase.

Verifica:
- Path feliz: distribuye a >=2 distros, alias distintos por distro, persiste.
- Cap de concentracion: rechaza distros que ya saturarian el catalogo.
- Insuficientes distros disponibles: levanta InsufficientDistributorsError.
- Failure parcial (un distro tira DistributorAPIError): sigue con el otro.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import structlog

from streaming_bot.application.distribution.alias_resolver import AliasResolver
from streaming_bot.application.distribution.dispatch_use_case import (
    ConcentrationCapExceededError,
    DispatchTrackRequest,
    InsufficientDistributorsError,
    MultiDistributorDispatchUseCase,
)
from streaming_bot.application.distribution.policy import DispatchPolicy
from streaming_bot.domain.distribution.distributor_id import DistributorId
from streaming_bot.domain.distribution.release import (
    Release,
    ReleaseStatus,
    ReleaseSubmission,
)
from streaming_bot.domain.ports.distributor_dispatcher import DistributorAPIError

# --- Helpers ----------------------------------------------------------------


def _request(*, track_id: str = "track-1") -> DispatchTrackRequest:
    return DispatchTrackRequest(
        track_id=track_id,
        title="Mi Primer Hit",
        audio_path=Path("/tmp/track.wav"),  # solo metadata
        release_date=date(2026, 5, 10),
        isrc="USAT22612345",
        duration_seconds=210,
    )


def _policy(**overrides: object) -> DispatchPolicy:
    base: dict[str, object] = {"min_distributors": 2, "max_concentration_pct": 0.25}
    base.update(overrides)
    return DispatchPolicy(**base)  # type: ignore[arg-type]


def _make_alias_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get.return_value = None
    repo.save.return_value = None
    return repo


def _make_releases_repo(
    *,
    counts: dict[DistributorId, int] | None = None,
    total: int = 0,
) -> AsyncMock:
    repo = AsyncMock()
    repo.count_by_distributor.return_value = dict(counts or {})
    repo.total_releases.return_value = total
    repo.save.return_value = None
    repo.save_submission.return_value = None
    return repo


class _FakeRouter:
    """Router fake que devuelve submissions o exceptions configurables."""

    def __init__(
        self,
        *,
        available: frozenset[DistributorId],
        outcomes: dict[DistributorId, ReleaseSubmission | Exception] | None = None,
    ) -> None:
        self._available = available
        self._outcomes = outcomes or {}
        self.last_releases: dict[DistributorId, Release] = {}
        self.dispatch_calls = 0

    @property
    def available_distributors(self) -> frozenset[DistributorId]:
        return self._available

    async def dispatch(
        self,
        releases_by_distributor: dict[DistributorId, Release],
    ) -> dict[DistributorId, ReleaseSubmission | Exception]:
        self.dispatch_calls += 1
        self.last_releases = dict(releases_by_distributor)
        results: dict[DistributorId, ReleaseSubmission | Exception] = {}
        for distributor, release in releases_by_distributor.items():
            override = self._outcomes.get(distributor)
            if override is not None:
                results[distributor] = override
                continue
            results[distributor] = ReleaseSubmission(
                submission_id=f"{distributor.value}-{release.release_id[:6]}",
                distributor=distributor,
                release_id=release.release_id,
                submitted_at=datetime.now(UTC),
                status=ReleaseStatus.SUBMITTED,
            )
        return results


@pytest.fixture
def alias_repo() -> AsyncMock:
    return _make_alias_repo()


@pytest.fixture
def releases_repo() -> AsyncMock:
    return _make_releases_repo()


@pytest.fixture
def use_case_factory(
    alias_repo: AsyncMock,
    releases_repo: AsyncMock,
) -> AsyncIterator[
    tuple[MultiDistributorDispatchUseCase, _FakeRouter, AsyncMock, AsyncMock]
]:
    """Crea un use case configurado con un router fake parametrizable."""

    def _build(
        *,
        available: frozenset[DistributorId] = frozenset(
            {DistributorId.DISTROKID, DistributorId.ROUTENOTE},
        ),
        policy: DispatchPolicy | None = None,
        outcomes: dict[DistributorId, ReleaseSubmission | Exception] | None = None,
    ) -> tuple[MultiDistributorDispatchUseCase, _FakeRouter, AsyncMock, AsyncMock]:
        router = _FakeRouter(available=available, outcomes=outcomes)
        resolver = AliasResolver(alias_repo=alias_repo, policy=policy or _policy())
        use_case = MultiDistributorDispatchUseCase(
            alias_resolver=resolver,
            dispatcher_router=router,
            releases_repo=releases_repo,
            logger=structlog.get_logger("test"),
        )
        return use_case, router, alias_repo, releases_repo

    yield _build  # type: ignore[misc]


class TestHappyPath:
    async def test_dispatches_to_two_distributors_with_distinct_aliases(
        self,
        use_case_factory: object,
    ) -> None:
        build = use_case_factory  # type: ignore[assignment]
        use_case, router, alias_repo, releases_repo = build()  # type: ignore[operator]

        result = await use_case.execute(_request(), _policy())

        assert len(result.succeeded) == 2
        assert not result.failed
        assert {o.distributor for o in result.succeeded} == {
            DistributorId.DISTROKID,
            DistributorId.ROUTENOTE,
        }
        # Aliases distintos por distro
        names = {o.release.artist_name for o in result.succeeded}
        assert len(names) == 2
        # Persistencia: 1 release y 1 submission por distro
        assert releases_repo.save.await_count == 2
        assert releases_repo.save_submission.await_count == 2
        assert alias_repo.save.await_count == 2
        assert router.dispatch_calls == 1


class TestConcentrationCap:
    async def test_skips_distributor_already_over_cap(
        self,
        use_case_factory: object,
        releases_repo: AsyncMock,
    ) -> None:
        # 100 releases existentes, 80 en DistroKid -> ya supera 25%.
        releases_repo.count_by_distributor.return_value = {
            DistributorId.DISTROKID: 80,
            DistributorId.ROUTENOTE: 20,
        }
        releases_repo.total_releases.return_value = 100

        build = use_case_factory  # type: ignore[assignment]
        use_case, _router, _alias_repo, _releases_repo = build(  # type: ignore[operator]
            available=frozenset(
                {
                    DistributorId.DISTROKID,
                    DistributorId.ROUTENOTE,
                    DistributorId.AMUSE,
                },
            ),
        )

        result = await use_case.execute(_request(), _policy(min_distributors=2))

        attempted = {o.distributor for o in result.succeeded}
        assert DistributorId.DISTROKID not in attempted
        assert DistributorId.DISTROKID in result.skipped_distributors
        assert len(result.succeeded) >= 2

    async def test_raises_when_all_candidates_over_cap(
        self,
        use_case_factory: object,
        releases_repo: AsyncMock,
    ) -> None:
        releases_repo.count_by_distributor.return_value = {
            DistributorId.DISTROKID: 90,
            DistributorId.ROUTENOTE: 90,
        }
        releases_repo.total_releases.return_value = 180

        build = use_case_factory  # type: ignore[assignment]
        use_case, _router, _alias_repo, _releases_repo = build(  # type: ignore[operator]
            available=frozenset(
                {DistributorId.DISTROKID, DistributorId.ROUTENOTE},
            ),
        )

        with pytest.raises(ConcentrationCapExceededError):
            await use_case.execute(_request(), _policy(max_concentration_pct=0.10))


class TestInsufficientDistributors:
    async def test_raises_when_fewer_adapters_than_min(
        self,
        use_case_factory: object,
    ) -> None:
        build = use_case_factory  # type: ignore[assignment]
        use_case, _router, _alias_repo, _releases_repo = build(  # type: ignore[operator]
            available=frozenset({DistributorId.DISTROKID}),
        )

        with pytest.raises(InsufficientDistributorsError):
            await use_case.execute(_request(), _policy(min_distributors=2))

    async def test_excluded_distributors_count_against_pool(
        self,
        use_case_factory: object,
    ) -> None:
        build = use_case_factory  # type: ignore[assignment]
        use_case, _router, _alias_repo, _releases_repo = build(  # type: ignore[operator]
            available=frozenset(
                {DistributorId.DISTROKID, DistributorId.ROUTENOTE},
            ),
            policy=_policy(
                excluded_distributors=frozenset({DistributorId.DISTROKID}),
            ),
        )

        with pytest.raises(InsufficientDistributorsError):
            await use_case.execute(
                _request(),
                _policy(
                    min_distributors=2,
                    excluded_distributors=frozenset({DistributorId.DISTROKID}),
                ),
            )


class TestPartialFailure:
    async def test_one_distributor_fails_others_succeed(
        self,
        use_case_factory: object,
        releases_repo: AsyncMock,
    ) -> None:
        build = use_case_factory  # type: ignore[assignment]
        use_case, _router, _alias_repo, _releases_repo = build(  # type: ignore[operator]
            available=frozenset(
                {DistributorId.DISTROKID, DistributorId.ROUTENOTE},
            ),
            outcomes={
                DistributorId.DISTROKID: DistributorAPIError("selector roto"),
            },
        )

        result = await use_case.execute(_request(), _policy())

        assert {o.distributor for o in result.succeeded} == {DistributorId.ROUTENOTE}
        assert {o.distributor for o in result.failed} == {DistributorId.DISTROKID}
        # Solo el OK persiste release y submission
        assert releases_repo.save.await_count == 1
        assert releases_repo.save_submission.await_count == 1
        # El error queda en el outcome con prefijo api_error:
        failed = result.failed[0]
        assert failed.error_message is not None
        assert failed.error_message.startswith("api_error:")
