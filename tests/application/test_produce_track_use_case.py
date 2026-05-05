"""Tests del ``ProduceTrackUseCase``.

Estrategia:
- Mockear todos los puertos con ``AsyncMock``.
- Verificar que el orden de llamadas es generate -> master -> cover ->
  enrich -> add y que el bundle devuelto contiene los artefactos.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from streaming_bot.application.catalog_pipeline.produce_track_use_case import (
    ProduceTrackUseCase,
)
from streaming_bot.domain.catalog_pipeline.metadata_pack import MetadataPack
from streaming_bot.domain.catalog_pipeline.raw_audio import AudioFormat, RawAudio
from streaming_bot.domain.catalog_pipeline.track_brief import TrackBrief
from streaming_bot.domain.ports.audio_mastering import MasteringProfile
from streaming_bot.domain.song import SongRole, SongTier
from streaming_bot.domain.value_objects import Country


def _brief() -> TrackBrief:
    return TrackBrief(
        niche="lo-fi",
        mood="rainy",
        bpm_range=(72, 80),
        duration_seconds=180,
        target_geos=(Country.US, Country.MX),
    )


def _raw(name: str, *, duration_ms: int = 180_000) -> RawAudio:
    return RawAudio(
        bytes_path=Path(f"/tmp/{name}.mp3"),
        format=AudioFormat.MP3,
        sample_rate=44_100,
        duration_ms=duration_ms,
    )


def _metadata() -> MetadataPack:
    return MetadataPack(
        title="Rain on Concrete",
        artist_alias="Lumen Drift",
        genre="lofi",
        subgenre="study-beats",
        tags=("lofi", "rain", "study", "calm"),
        description="Suaves pulsos lo-fi con lluvia y atmosferas urbanas.",
        cover_art_path=Path("/tmp/track-1.cover.png"),
    )


@pytest.fixture
def mocks() -> dict[str, AsyncMock]:
    music = AsyncMock()
    music.generate.return_value = _raw("track-1")

    mastering = AsyncMock()
    mastering.master.return_value = _raw("track-1.mastered")

    cover = AsyncMock()
    cover.generate.return_value = Path("/tmp/track-1.cover.png")

    metadata = AsyncMock()
    metadata.enrich.return_value = _metadata()

    songs = AsyncMock()
    songs.add.return_value = None

    return {
        "music": music,
        "mastering": mastering,
        "cover": cover,
        "metadata": metadata,
        "songs": songs,
    }


def _build_use_case(
    mocks: dict[str, AsyncMock],
    *,
    track_id: str = "track-1",
) -> ProduceTrackUseCase:
    track_id_factory = MagicMock(return_value=track_id)
    return ProduceTrackUseCase(
        music_generator=mocks["music"],
        mastering=mocks["mastering"],
        cover_generator=mocks["cover"],
        metadata_generator=mocks["metadata"],
        songs=mocks["songs"],
        mastering_profile=MasteringProfile.spotify(),
        logger=structlog.get_logger("test"),
        track_id_factory=track_id_factory,
    )


class TestProduceTrackUseCase:
    async def test_pipeline_executes_steps_in_order(
        self,
        mocks: dict[str, AsyncMock],
    ) -> None:
        use_case = _build_use_case(mocks)
        brief = _brief()

        produced = await use_case.execute(brief)

        assert produced.track_id == "track-1"
        assert produced.metadata.title == "Rain on Concrete"
        mocks["music"].generate.assert_awaited_once_with(brief, track_id="track-1")
        mocks["mastering"].master.assert_awaited_once()
        mocks["cover"].generate.assert_awaited_once_with(brief, track_id="track-1")
        mocks["metadata"].enrich.assert_awaited_once_with(
            brief,
            mocks["mastering"].master.return_value,
            cover_art_path=Path("/tmp/track-1.cover.png"),
        )
        mocks["songs"].add.assert_awaited_once()

    async def test_uses_mastered_raw_for_metadata_enrichment(
        self,
        mocks: dict[str, AsyncMock],
    ) -> None:
        use_case = _build_use_case(mocks)
        await use_case.execute(_brief())

        passed_raw = mocks["metadata"].enrich.call_args.args[1]
        assert passed_raw is mocks["mastering"].master.return_value

    async def test_persisted_song_uses_metadata_fields(
        self,
        mocks: dict[str, AsyncMock],
    ) -> None:
        use_case = _build_use_case(mocks)
        produced = await use_case.execute(_brief())

        song = produced.song
        assert song.title == "Rain on Concrete"
        assert song.artist_name == "Lumen Drift"
        assert song.role is SongRole.TARGET
        assert song.tier is SongTier.LOW
        assert song.spotify_uri.startswith("catalog:track:")
        assert song.artist_uri == "catalog:artist:lumen-drift"
        assert song.metadata.duration_seconds == 180

    async def test_propagates_generator_failure(
        self,
        mocks: dict[str, AsyncMock],
    ) -> None:
        mocks["music"].generate.side_effect = RuntimeError("suno boom")
        use_case = _build_use_case(mocks)

        with pytest.raises(RuntimeError, match="suno boom"):
            await use_case.execute(_brief())

        mocks["mastering"].master.assert_not_awaited()
        mocks["songs"].add.assert_not_awaited()
