"""Tests del ``ReelsGeneratorService``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from streaming_bot.application.meta.reels_generator import ReelsGeneratorService
from streaming_bot.domain.meta.smart_link import SmartLink
from streaming_bot.domain.value_objects import Country


def _smart_link() -> SmartLink:
    return SmartLink(
        short_id="aB3xZ",
        target_dsps={Country.PE: {"spotify": "https://open.spotify.com/track/x"}},
        track_uri="catalog:track:abc",
    )


class TestReelsGeneratorService:
    async def test_pipeline_executes_in_order(self, tmp_path: Path) -> None:
        stock_clip = tmp_path / "stock-rain.mp4"
        stock_clip.write_bytes(b"\x00")
        audio = tmp_path / "track.mp3"
        audio.write_bytes(b"\x00")

        stock_repo = AsyncMock()
        stock_repo.pick_clip.return_value = stock_clip

        builder = AsyncMock()
        built = tmp_path / "reel-acc-aB3xZ.mp4"
        built.write_bytes(b"\x00")
        builder.build.return_value = built

        captions = AsyncMock()
        captions.generate.return_value = ("rainy nights", ("lofi", "study"))

        service = ReelsGeneratorService(
            stock_footage=stock_repo,
            reel_builder=builder,
            caption_generator=captions,
            output_dir=tmp_path,
        )

        bundle = await service.generate(
            account_id="acc",
            track_uri="catalog:track:abc",
            track_title="Rain on Concrete",
            artist_name="Lumen Drift",
            artist_uri="catalog:artist:lumen-drift",
            audio_track_path=audio,
            niche="lo-fi",
            mood="rainy",
            smart_link=_smart_link(),
            smart_link_base_url="https://link.example.com/",
            smart_link_country=Country.PE,
        )

        stock_repo.pick_clip.assert_awaited_once_with(niche="lo-fi", mood="rainy")
        builder.build.assert_awaited_once()
        captions.generate.assert_awaited_once_with(
            track_title="Rain on Concrete",
            artist_name="Lumen Drift",
            niche="lo-fi",
            mood="rainy",
        )
        assert bundle.reel.account_id == "acc"
        assert bundle.reel.audio_track_uri == "catalog:track:abc"
        assert bundle.reel.video_path == built
        assert "rainy nights" in bundle.reel.caption
        assert bundle.reel.smart_link == "https://link.example.com/aB3xZ"
        assert bundle.reel.hashtags == ("lofi", "study")

    async def test_caption_includes_smart_link_within_200_chars(self, tmp_path: Path) -> None:
        stock = tmp_path / "s.mp4"
        stock.write_bytes(b"\x00")
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")

        stock_repo = AsyncMock()
        stock_repo.pick_clip.return_value = stock
        builder = AsyncMock()
        builder.build.return_value = tmp_path / "reel.mp4"
        captions = AsyncMock()
        long_caption = "x" * 195
        captions.generate.return_value = (long_caption, ())

        service = ReelsGeneratorService(
            stock_footage=stock_repo,
            reel_builder=builder,
            caption_generator=captions,
            output_dir=tmp_path,
        )

        bundle = await service.generate(
            account_id="acc",
            track_uri="catalog:track:abc",
            track_title="t",
            artist_name="a",
            artist_uri="catalog:artist:a",
            audio_track_path=audio,
            niche="lo-fi",
            smart_link=_smart_link(),
            smart_link_base_url="https://link.example.com/",
            smart_link_country=Country.PE,
        )

        assert len(bundle.reel.caption) <= 200
        assert "https://link.example.com/aB3xZ" in bundle.reel.caption

    async def test_invalid_country_type_raises(self, tmp_path: Path) -> None:
        stock_repo = AsyncMock()
        builder = AsyncMock()
        captions = AsyncMock()
        captions.generate.return_value = ("c", ())
        service = ReelsGeneratorService(
            stock_footage=stock_repo,
            reel_builder=builder,
            caption_generator=captions,
            output_dir=tmp_path,
        )
        with pytest.raises(TypeError, match="Country"):
            await service.generate(
                account_id="acc",
                track_uri="catalog:track:abc",
                track_title="t",
                artist_name="a",
                artist_uri="catalog:artist:a",
                audio_track_path=tmp_path / "a.mp3",
                niche="lo-fi",
                smart_link=_smart_link(),
                smart_link_base_url="https://x/",
                smart_link_country="PE",
            )

    async def test_normalize_hashtags_strips_hash_prefix(self) -> None:
        result = ReelsGeneratorService._normalize_hashtags(["#lofi", " study ", "", "#Rain"])
        assert result == ("lofi", "study", "rain")

    async def test_inject_smart_link_truncates_long_caption(self) -> None:
        link = "https://link.example.com/aB3xZ"
        injected = ReelsGeneratorService._inject_smart_link("x" * 250, link)
        assert len(injected) <= 200
        assert injected.endswith(link)
