"""Tests de ArtistUpserter y LabelUpserter (caching/idempotencia)."""

from __future__ import annotations

import pytest

from streaming_bot.application.import_catalog.upsert import (
    ArtistUpserter,
    LabelUpserter,
)
from streaming_bot.domain.artist import Artist
from streaming_bot.domain.label import DistributorType, Label
from tests.application.import_catalog.fakes import (
    FakeArtistRepository,
    FakeLabelRepository,
)


@pytest.mark.asyncio
async def test_artist_upserter_creates_once_then_caches() -> None:
    repo = FakeArtistRepository()
    upserter = ArtistUpserter(repo)

    a1 = await upserter.upsert(name="Tony Jaxx")
    a2 = await upserter.upsert(name="Tony Jaxx")
    a3 = await upserter.upsert(name="tony jaxx")

    assert a1.id == a2.id == a3.id
    assert upserter.stats.created == 1
    assert upserter.stats.found == 2
    # Solo 1 query a get_by_name (despues hay cache)
    assert repo.calls["get_by_name"] == 1
    assert repo.calls["save"] == 1


@pytest.mark.asyncio
async def test_artist_upserter_finds_existing_by_uri() -> None:
    repo = FakeArtistRepository()
    pre = Artist.new(name="Pre", spotify_uri="spotify:artist:abc")
    await repo.save(pre)
    upserter = ArtistUpserter(repo)

    found = await upserter.upsert(name="Pre", spotify_uri="spotify:artist:abc")
    assert found.id == pre.id
    assert upserter.stats.created == 0


@pytest.mark.asyncio
async def test_artist_upserter_dry_run_does_not_save() -> None:
    repo = FakeArtistRepository()
    upserter = ArtistUpserter(repo, dry_run=True)
    artist = await upserter.upsert(name="Ghost")
    assert artist.name == "Ghost"
    assert repo.calls.get("save", 0) == 0
    assert upserter.stats.created == 1


@pytest.mark.asyncio
async def test_artist_upserter_links_label_when_found_without_one() -> None:
    repo = FakeArtistRepository()
    pre = Artist.new(name="Solo")
    await repo.save(pre)
    upserter = ArtistUpserter(repo)

    found = await upserter.upsert(name="Solo", label_id="label-xyz")
    assert found.label_id == "label-xyz"
    # save invocado para actualizar (1 inicial + 1 update)
    assert repo.calls["save"] == 2


@pytest.mark.asyncio
async def test_label_upserter_caches_by_name_and_distributor() -> None:
    repo = FakeLabelRepository()
    upserter = LabelUpserter(repo)

    a = await upserter.upsert(name="Worldwide Hits", distributor=DistributorType.AICOM)
    b = await upserter.upsert(name="Worldwide Hits", distributor=DistributorType.AICOM)
    assert a.id == b.id
    assert upserter.stats.created == 1
    assert upserter.stats.found == 1


@pytest.mark.asyncio
async def test_label_upserter_returns_existing() -> None:
    repo = FakeLabelRepository()
    pre = Label.new(name="Existing", distributor=DistributorType.DISTROKID)
    await repo.save(pre)
    upserter = LabelUpserter(repo)
    found = await upserter.upsert(name="Existing", distributor=DistributorType.DISTROKID)
    assert found.id == pre.id
    assert upserter.stats.created == 0


@pytest.mark.asyncio
async def test_label_upserter_dry_run_skips_save() -> None:
    repo = FakeLabelRepository()
    upserter = LabelUpserter(repo, dry_run=True)
    await upserter.upsert(name="Phantom", distributor=DistributorType.AICOM)
    assert repo.calls.get("save", 0) == 0


@pytest.mark.asyncio
async def test_artist_upserter_avoids_n_plus_1_for_repeated_names() -> None:
    repo = FakeArtistRepository()
    upserter = ArtistUpserter(repo)
    # Simular 100 filas de la misma cancion con el mismo artista (ej. distintos
    # territorios/meses): el cache evita 100 queries.
    for _ in range(100):
        await upserter.upsert(name="HotShot")
    assert repo.calls["get_by_name"] == 1
    assert repo.calls["save"] == 1
