"""Tests del dominio ``Reel`` y ``SmartLink``."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from streaming_bot.domain.meta.reel import Reel, ReelMetrics
from streaming_bot.domain.meta.smart_link import SmartLink
from streaming_bot.domain.value_objects import Country


def _reel(*, caption: str = "rainy lo-fi tonight", hashtags: tuple[str, ...] = ("lofi",)) -> Reel:
    return Reel.new(
        account_id="acc-1",
        audio_track_uri="catalog:track:abc",
        video_path=Path("/tmp/reel-1.mp4"),
        caption=caption,
        hashtags=hashtags,
        smart_link="https://link.example.com/aB3xZ",
    )


class TestReelInvariants:
    def test_new_creates_reel(self) -> None:
        reel = _reel()
        assert reel.is_posted is False
        assert reel.metrics.plays == 0

    def test_empty_caption_raises(self) -> None:
        with pytest.raises(ValueError, match="caption"):
            _reel(caption="")

    def test_caption_over_200_chars_raises(self) -> None:
        with pytest.raises(ValueError, match="200 chars"):
            _reel(caption="x" * 201)

    def test_full_caption_concatenates_hashtags(self) -> None:
        reel = _reel(caption="vibey", hashtags=("lofi", "study", "rain"))
        full = reel.full_caption()
        assert "vibey" in full
        assert "#lofi" in full
        assert "#study" in full
        assert "#rain" in full

    def test_full_caption_handles_hashtag_prefix(self) -> None:
        reel = _reel(hashtags=("#already", "tag"))
        full = reel.full_caption()
        assert "#already" in full
        assert "#tag" in full
        assert "##already" not in full


class TestReelTransitions:
    def test_mark_posted_sets_metadata(self) -> None:
        reel = _reel()
        ts = datetime.now(UTC)
        reel.mark_posted(media_id="ig-pk-123", posted_at=ts)
        assert reel.is_posted is True
        assert reel.media_id == "ig-pk-123"
        assert reel.posted_at == ts

    def test_update_metrics_replaces(self) -> None:
        reel = _reel()
        reel.update_metrics(ReelMetrics(plays=100, shares=5, saves=8, likes=20, comments=3))
        assert reel.plays == 100
        assert reel.shares == 5
        assert reel.saves == 8


class TestSmartLink:
    def test_url_for_returns_short_url(self) -> None:
        link = SmartLink(
            short_id="aB3xZ",
            target_dsps={Country.PE: {"spotify": "https://open.spotify.com/track/x"}},
            track_uri="catalog:track:x",
        )
        assert link.url_for(country=Country.PE, base_url="https://link.example.com/") == (
            "https://link.example.com/aB3xZ"
        )

    def test_resolve_country_dsp(self) -> None:
        link = SmartLink(
            short_id="aB3xZ",
            target_dsps={
                Country.PE: {"spotify": "https://spotify/x", "deezer": "https://deezer/x"},
                Country.US: {"apple_music": "https://am/x"},
            },
            track_uri="catalog:track:x",
        )
        assert link.resolve(country=Country.PE, dsp="spotify") == "https://spotify/x"
        assert link.resolve(country=Country.PE) == "https://spotify/x"
        assert link.resolve(country=Country.US, dsp="apple_music") == "https://am/x"

    def test_resolve_unknown_country_returns_none(self) -> None:
        link = SmartLink(
            short_id="aB3xZ",
            target_dsps={Country.PE: {"spotify": "https://spotify/x"}},
            track_uri="catalog:track:x",
        )
        assert link.resolve(country=Country.JP) is None

    def test_empty_targets_raises(self) -> None:
        with pytest.raises(ValueError, match="target_dsps"):
            SmartLink(short_id="x", target_dsps={}, track_uri="catalog:track:y")

    def test_empty_short_id_raises(self) -> None:
        with pytest.raises(ValueError, match="short_id"):
            SmartLink(
                short_id="",
                target_dsps={Country.PE: {"spotify": "https://x"}},
                track_uri="catalog:track:y",
            )
