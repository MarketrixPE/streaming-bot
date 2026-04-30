"""Tests end-to-end del ImportCatalogService con fakes en memoria.

Cubren: flujo completo, idempotencia, dry-run, deteccion de flagged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import structlog

from streaming_bot.application.import_catalog.import_service import (
    ImportCatalogService,
)
from streaming_bot.application.import_catalog.tier_classifier import TierClassifier
from streaming_bot.domain.artist import Artist
from streaming_bot.domain.label import DistributorType, Label
from streaming_bot.domain.song import SongTier
from tests.application.import_catalog.fakes import (
    FakeArtistRepository,
    FakeLabelRepository,
    FakeSongRepository,
)
from tests.fixtures.import_catalog.builders import (
    make_aicom_xlsx,
    make_flagged_csv,
)


@pytest.fixture
def logger() -> structlog.stdlib.BoundLogger:
    log: structlog.stdlib.BoundLogger = structlog.get_logger("test")
    return log


@pytest.fixture
def fakes() -> tuple[FakeArtistRepository, FakeLabelRepository, FakeSongRepository]:
    return FakeArtistRepository(), FakeLabelRepository(), FakeSongRepository()


@pytest.mark.asyncio
async def test_end_to_end_aicom_import_creates_entities(
    tmp_path: Path,
    fakes: tuple[FakeArtistRepository, FakeLabelRepository, FakeSongRepository],
    logger: structlog.stdlib.BoundLogger,
) -> None:
    artists, labels, songs = fakes
    file = tmp_path / "aicom.xlsx"
    make_aicom_xlsx(file)

    service = ImportCatalogService(
        artists=artists,
        labels=labels,
        songs=songs,
        classifier=TierClassifier(),
        logger=logger,
    )
    summary = await service.import_file(file, distributor=DistributorType.AICOM)

    assert summary.rows_seen == 2
    assert summary.songs_created == 2
    assert summary.songs_updated == 0
    assert summary.artists_created >= 2
    assert summary.labels_created == 1
    assert summary.flagged_count == 0
    # Distribucion: deben caer en MID/LOW segun avg
    assert sum(summary.by_tier.values()) == 2


@pytest.mark.asyncio
async def test_idempotency_running_import_twice_no_duplicates(
    tmp_path: Path,
    fakes: tuple[FakeArtistRepository, FakeLabelRepository, FakeSongRepository],
    logger: structlog.stdlib.BoundLogger,
) -> None:
    artists, labels, songs = fakes
    file = tmp_path / "aicom.xlsx"
    make_aicom_xlsx(file)
    service = ImportCatalogService(
        artists=artists,
        labels=labels,
        songs=songs,
        classifier=TierClassifier(),
        logger=logger,
    )

    first = await service.import_file(file, distributor=DistributorType.AICOM)
    second = await service.import_file(file, distributor=DistributorType.AICOM)

    assert first.songs_created == 2
    assert second.songs_created == 0
    assert second.songs_updated == 2
    assert second.artists_created == 0
    assert second.labels_created == 0
    # Repo de songs solo tiene 2 items
    assert len(await songs.list_all()) == 2
    # Repo de artists no se infla en el segundo run
    artist_count_first = len(await artists.list_all())
    third = await service.import_file(file, distributor=DistributorType.AICOM)
    assert third.songs_created == 0
    assert len(await artists.list_all()) == artist_count_first


@pytest.mark.asyncio
async def test_dry_run_does_not_persist(
    tmp_path: Path,
    fakes: tuple[FakeArtistRepository, FakeLabelRepository, FakeSongRepository],
    logger: structlog.stdlib.BoundLogger,
) -> None:
    artists, labels, songs = fakes
    file = tmp_path / "aicom.xlsx"
    make_aicom_xlsx(file)

    service = ImportCatalogService(
        artists=artists,
        labels=labels,
        songs=songs,
        classifier=TierClassifier(),
        logger=logger,
    )
    summary = await service.import_file(
        file,
        distributor=DistributorType.AICOM,
        dry_run=True,
    )
    assert summary.dry_run is True
    assert summary.rows_seen == 2
    # En dry run el upserter cuenta los "creates" pero no escribe
    assert artists.calls.get("save", 0) == 0
    assert labels.calls.get("save", 0) == 0
    assert songs.calls.get("add", 0) == 0


@pytest.mark.asyncio
async def test_flagged_song_marks_tier_and_increments(
    tmp_path: Path,
    fakes: tuple[FakeArtistRepository, FakeLabelRepository, FakeSongRepository],
    logger: structlog.stdlib.BoundLogger,
) -> None:
    artists, labels, songs = fakes
    file = tmp_path / "aicom.xlsx"
    make_aicom_xlsx(file)
    flagged_path = tmp_path / "flagged.csv"
    # ISRC del song1 en el fixture
    make_flagged_csv(flagged_path, isrcs=["QZMZ92544149"])

    service = ImportCatalogService(
        artists=artists,
        labels=labels,
        songs=songs,
        classifier=TierClassifier(),
        logger=logger,
        flagged_oct2025_path=flagged_path,
    )
    summary = await service.import_file(file, distributor=DistributorType.AICOM)
    assert summary.flagged_count == 1
    assert summary.by_tier.get(SongTier.FLAGGED, 0) == 1

    flagged_song = await songs.get_by_isrc("QZMZ92544149")
    assert flagged_song is not None
    assert flagged_song.spike_oct2025_flag is True
    assert flagged_song.tier == SongTier.FLAGGED


@pytest.mark.asyncio
async def test_explicit_artist_and_label_override(
    tmp_path: Path,
    fakes: tuple[FakeArtistRepository, FakeLabelRepository, FakeSongRepository],
    logger: structlog.stdlib.BoundLogger,
) -> None:
    artists, labels, songs = fakes
    file = tmp_path / "aicom.xlsx"
    make_aicom_xlsx(file)

    forced_artist = Artist.new(name="Forced Artist")
    forced_label = Label.new(name="Forced Label", distributor=DistributorType.AICOM)
    await artists.save(forced_artist)
    await labels.save(forced_label)

    service = ImportCatalogService(
        artists=artists,
        labels=labels,
        songs=songs,
        classifier=TierClassifier(),
        logger=logger,
    )
    summary = await service.import_file(
        file,
        artist_id=forced_artist.id,
        label_id=forced_label.id,
        distributor=DistributorType.AICOM,
    )
    assert summary.songs_created == 2
    for song in await songs.list_all():
        assert song.primary_artist_id == forced_artist.id
        assert song.label_id == forced_label.id
        assert song.artist_name == forced_artist.name


@pytest.mark.asyncio
async def test_unknown_format_returns_summary_with_error(
    tmp_path: Path,
    fakes: tuple[FakeArtistRepository, FakeLabelRepository, FakeSongRepository],
    logger: structlog.stdlib.BoundLogger,
) -> None:
    artists, labels, songs = fakes
    file = tmp_path / "garbage.txt"
    file.write_text("nothing structured here\n", encoding="utf-8")

    service = ImportCatalogService(
        artists=artists,
        labels=labels,
        songs=songs,
        classifier=TierClassifier(),
        logger=logger,
    )
    summary = await service.import_file(file)
    assert summary.rows_seen == 0
    assert summary.errors
