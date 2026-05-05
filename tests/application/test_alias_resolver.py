"""Tests del AliasResolver.

Verifica:
- Determinismo: mismo (track_id, distributor) -> mismo alias entre runs.
- Distribuidores distintos -> aliases distintos para el mismo track.
- Reuso: si el repo ya tiene alias persistido, lo devuelve sin tocar el pool.
- Persistencia: cuando crea uno nuevo lo guarda.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from streaming_bot.application.distribution.alias_resolver import (
    AliasNamingTemplate,
    AliasResolver,
)
from streaming_bot.application.distribution.policy import DispatchPolicy
from streaming_bot.domain.distribution.distributor_id import DistributorId
from streaming_bot.domain.distribution.release import ArtistAlias


def _policy(**overrides: object) -> DispatchPolicy:
    base: dict[str, object] = {
        "min_distributors": 2,
        "max_concentration_pct": 0.25,
        "label_name": "Worldwide Hits",
    }
    base.update(overrides)
    return DispatchPolicy(**base)  # type: ignore[arg-type]


class TestAliasNamingTemplate:
    def test_same_inputs_yield_same_name(self) -> None:
        template = AliasNamingTemplate(
            adjectives=("Cosmic", "Velvet", "Crystal"),
            nouns=("Beats", "Vibes", "Wave"),
            seed=42,
        )
        first = template.build_name(track_id="t-1", distributor=DistributorId.DISTROKID)
        second = template.build_name(track_id="t-1", distributor=DistributorId.DISTROKID)
        assert first == second

    def test_different_distributor_yields_different_name(self) -> None:
        template = AliasNamingTemplate(
            adjectives=("Cosmic", "Velvet", "Crystal"),
            nouns=("Beats", "Vibes", "Wave"),
            seed=42,
        )
        a = template.build_name(track_id="t-1", distributor=DistributorId.DISTROKID)
        b = template.build_name(track_id="t-1", distributor=DistributorId.ROUTENOTE)
        assert a != b

    def test_empty_pools_raises(self) -> None:
        with pytest.raises(ValueError, match="adjectives y nouns"):
            AliasNamingTemplate(adjectives=(), nouns=("Beats",))

    def test_name_format_contains_two_words_and_suffix(self) -> None:
        template = AliasNamingTemplate(
            adjectives=("Cosmic",),
            nouns=("Beats",),
            seed=0,
        )
        name = template.build_name(track_id="t-1", distributor=DistributorId.DISTROKID)
        parts = name.split(" ")
        assert len(parts) == 3
        assert parts[0] == "Cosmic"
        assert parts[1] == "Beats"
        # Suffix son 2 hex chars uppercase
        assert len(parts[2]) == 2
        assert all(c in "0123456789ABCDEF" for c in parts[2])


class TestAliasResolver:
    @pytest.fixture
    def repo(self) -> AsyncMock:
        repo = AsyncMock()
        repo.get.return_value = None
        repo.save.return_value = None
        repo.list_for_track.return_value = []
        repo.list_for_distributor.return_value = []
        return repo

    async def test_creates_alias_when_missing_and_persists(self, repo: AsyncMock) -> None:
        resolver = AliasResolver(alias_repo=repo, policy=_policy(rng_seed=1))
        resolved = await resolver.resolve(
            track_id="track-1",
            distributor=DistributorId.DISTROKID,
        )
        assert resolved.created is True
        assert resolved.alias.track_id == "track-1"
        assert resolved.alias.distributor is DistributorId.DISTROKID
        assert resolved.alias.label_name == "Worldwide Hits"
        repo.save.assert_awaited_once_with(resolved.alias)

    async def test_reuses_persisted_alias(self, repo: AsyncMock) -> None:
        existing = ArtistAlias(
            track_id="track-1",
            distributor=DistributorId.DISTROKID,
            alias_name="Persisted Name 00",
            label_name="Worldwide Hits",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        repo.get.return_value = existing

        resolver = AliasResolver(alias_repo=repo, policy=_policy())
        resolved = await resolver.resolve(
            track_id="track-1",
            distributor=DistributorId.DISTROKID,
        )

        assert resolved.created is False
        assert resolved.alias is existing
        repo.save.assert_not_awaited()

    async def test_distinct_alias_per_distributor(self, repo: AsyncMock) -> None:
        resolver = AliasResolver(alias_repo=repo, policy=_policy(rng_seed=7))
        a = await resolver.resolve(track_id="track-1", distributor=DistributorId.DISTROKID)
        b = await resolver.resolve(track_id="track-1", distributor=DistributorId.ROUTENOTE)
        assert a.alias.alias_name != b.alias.alias_name

    async def test_dedicated_pool_per_distributor_used(self, repo: AsyncMock) -> None:
        policy = _policy(
            alias_pool_per_distributor={
                DistributorId.DISTROKID: ("Brutal", "Heavy"),
            },
            alias_adjective_pool=("Cosmic", "Velvet"),
            alias_noun_pool=("Beats", "Vibes"),
            rng_seed=3,
        )
        resolver = AliasResolver(alias_repo=repo, policy=policy)

        resolved = await resolver.resolve(
            track_id="track-X",
            distributor=DistributorId.DISTROKID,
        )
        first_word = resolved.alias.alias_name.split(" ")[0]
        assert first_word in {"Brutal", "Heavy"}
