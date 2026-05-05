"""Tests del ``CrossPlatformSpilloverOrchestrator``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from streaming_bot.application.meta.account_provisioning import (
    InstagramAccountProvisioningService,
    ProvisioningResult,
)
from streaming_bot.application.meta.reels_generator import GeneratedReel
from streaming_bot.application.meta.spillover_orchestrator import (
    CrossPlatformSpilloverOrchestrator,
    IReelRepository,
)
from streaming_bot.domain.artist import Artist
from streaming_bot.domain.meta.instagram_account import (
    InstagramAccount,
    InstagramAccountStatus,
)
from streaming_bot.domain.meta.reel import Reel
from streaming_bot.domain.meta.smart_link import SmartLink
from streaming_bot.domain.ports.instagram_client import (
    InstagramChallengeRequired,
    InstagramMediaResult,
    InstagramSessionToken,
)
from streaming_bot.domain.value_objects import Country

if TYPE_CHECKING:
    pass


def _artist() -> Artist:
    return Artist.new(name="Lumen Drift", spotify_uri="spotify:artist:xyz")


def _account_active() -> InstagramAccount:
    a = InstagramAccount.new(
        username="lumen_drift_ig",
        persona_id="p1",
        artist_uri="spotify:artist:xyz",
        device_fingerprint={"device_id": "uuid-1"},
    )
    a.mark_active()
    return a


def _smart_link() -> SmartLink:
    return SmartLink(
        short_id="aB3xZ",
        target_dsps={Country.PE: {"spotify": "https://spotify/x"}},
        track_uri="catalog:track:abc",
    )


def _reel(account_id: str, video: Path) -> Reel:
    return Reel.new(
        account_id=account_id,
        audio_track_uri="catalog:track:abc",
        video_path=video,
        caption="rainy nights",
        hashtags=("lofi",),
        smart_link="https://link.example.com/aB3xZ",
    )


class FakeReelRepository(IReelRepository):
    def __init__(self) -> None:
        self.added: list[Reel] = []
        self.updated: list[Reel] = []

    async def add(self, reel: Reel) -> None:
        self.added.append(reel)

    async def update(self, reel: Reel) -> None:
        self.updated.append(reel)

    async def list_by_account(self, account_id: str) -> list[Reel]:
        return [r for r in self.added if r.account_id == account_id]


@pytest.fixture
def setup_orchestrator(tmp_path: Path) -> dict[str, object]:
    account = _account_active()

    provisioning = AsyncMock(spec=InstagramAccountProvisioningService)
    provisioning.provision_for_artist.return_value = ProvisioningResult(
        account=account, created=False,
    )

    smart_link = _smart_link()
    smart_link_provider = AsyncMock()
    smart_link_provider.create_link.return_value = smart_link

    video = tmp_path / "reel.mp4"
    video.write_bytes(b"\x00")
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"\x00")
    bundle = GeneratedReel(
        reel=_reel(account.id, video),
        stock_clip_path=tmp_path / "stock.mp4",
        audio_track_path=audio,
    )
    reels_gen = AsyncMock()
    reels_gen.generate.return_value = bundle

    instagram = AsyncMock()
    instagram.login.return_value = InstagramSessionToken(
        username=account.username, settings_json="{}",
    )
    instagram.post_reel.return_value = InstagramMediaResult(
        media_id="ig-001", code="abc", caption="cap",
    )
    instagram.post_story.return_value = InstagramMediaResult(
        media_id="ig-story-001", code="def", caption="",
    )
    instagram.get_media_metrics.return_value = {
        "plays": 100, "shares": 5, "saves": 8, "likes": 20, "comments": 3,
    }

    reels_repo = FakeReelRepository()

    async def credentials(_username: str) -> tuple[str, InstagramSessionToken | None]:
        return "secret-pw", None

    orchestrator = CrossPlatformSpilloverOrchestrator(
        provisioning=provisioning,
        reels_generator=reels_gen,
        smart_link_provider=smart_link_provider,
        instagram_client=instagram,
        reels=reels_repo,
        credentials_resolver=credentials,
        smart_link_base_url="https://link.example.com/",
    )
    return {
        "orchestrator": orchestrator,
        "account": account,
        "instagram": instagram,
        "reels_gen": reels_gen,
        "reels_repo": reels_repo,
        "smart_link_provider": smart_link_provider,
        "audio": audio,
    }


class TestSpilloverHappyPath:
    async def test_full_cycle_marks_reel_posted(
        self,
        setup_orchestrator: dict[str, object],
    ) -> None:
        orchestrator: CrossPlatformSpilloverOrchestrator = setup_orchestrator[  # type: ignore[assignment]
            "orchestrator"
        ]
        instagram: AsyncMock = setup_orchestrator["instagram"]  # type: ignore[assignment]
        reels_repo: FakeReelRepository = setup_orchestrator["reels_repo"]  # type: ignore[assignment]
        audio: Path = setup_orchestrator["audio"]  # type: ignore[assignment]
        artist = _artist()

        result = await orchestrator.run_cycle(
            artist=artist,
            track_uri="catalog:track:abc",
            track_title="Rain",
            artist_name="Lumen Drift",
            audio_track_path=audio,
            niche="lo-fi",
            target_dsps={Country.PE: {"spotify": "https://spotify/x"}},
            primary_country=Country.PE,
        )

        assert result.posted is True
        assert result.failure_reason is None
        instagram.login.assert_awaited_once()
        instagram.post_reel.assert_awaited_once()
        instagram.post_story.assert_awaited_once()
        instagram.get_media_metrics.assert_awaited_once()

        assert len(reels_repo.added) == 1
        assert len(reels_repo.updated) >= 1
        added_reel = reels_repo.added[0]
        assert added_reel.is_posted is True
        assert added_reel.media_id == "ig-001"
        assert added_reel.metrics.plays == 100


class TestSpilloverFailures:
    async def test_account_not_postable_short_circuits(
        self,
        setup_orchestrator: dict[str, object],
    ) -> None:
        orchestrator: CrossPlatformSpilloverOrchestrator = setup_orchestrator[  # type: ignore[assignment]
            "orchestrator"
        ]
        account: InstagramAccount = setup_orchestrator["account"]  # type: ignore[assignment]
        instagram: AsyncMock = setup_orchestrator["instagram"]  # type: ignore[assignment]
        audio: Path = setup_orchestrator["audio"]  # type: ignore[assignment]
        account.mark_challenge("test")

        result = await orchestrator.run_cycle(
            artist=_artist(),
            track_uri="catalog:track:abc",
            track_title="t",
            artist_name="a",
            audio_track_path=audio,
            niche="lo-fi",
            target_dsps={Country.PE: {"spotify": "https://spotify/x"}},
            primary_country=Country.PE,
        )
        assert result.posted is False
        assert "challenge" in (result.failure_reason or "")
        instagram.login.assert_not_awaited()
        instagram.post_reel.assert_not_awaited()

    async def test_login_challenge_marks_account(
        self,
        setup_orchestrator: dict[str, object],
    ) -> None:
        orchestrator: CrossPlatformSpilloverOrchestrator = setup_orchestrator[  # type: ignore[assignment]
            "orchestrator"
        ]
        instagram: AsyncMock = setup_orchestrator["instagram"]  # type: ignore[assignment]
        account: InstagramAccount = setup_orchestrator["account"]  # type: ignore[assignment]
        audio: Path = setup_orchestrator["audio"]  # type: ignore[assignment]
        instagram.login.side_effect = InstagramChallengeRequired("checkpoint")

        result = await orchestrator.run_cycle(
            artist=_artist(),
            track_uri="catalog:track:abc",
            track_title="t",
            artist_name="a",
            audio_track_path=audio,
            niche="lo-fi",
            target_dsps={Country.PE: {"spotify": "https://spotify/x"}},
            primary_country=Country.PE,
        )
        assert result.posted is False
        assert "challenge_required" in (result.failure_reason or "")
        assert account.status is InstagramAccountStatus.CHALLENGE
        instagram.post_reel.assert_not_awaited()

    async def test_post_reel_challenge_marks_account(
        self,
        setup_orchestrator: dict[str, object],
    ) -> None:
        orchestrator: CrossPlatformSpilloverOrchestrator = setup_orchestrator[  # type: ignore[assignment]
            "orchestrator"
        ]
        instagram: AsyncMock = setup_orchestrator["instagram"]  # type: ignore[assignment]
        account: InstagramAccount = setup_orchestrator["account"]  # type: ignore[assignment]
        audio: Path = setup_orchestrator["audio"]  # type: ignore[assignment]
        instagram.post_reel.side_effect = InstagramChallengeRequired("rate limit")

        result = await orchestrator.run_cycle(
            artist=_artist(),
            track_uri="catalog:track:abc",
            track_title="t",
            artist_name="a",
            audio_track_path=audio,
            niche="lo-fi",
            target_dsps={Country.PE: {"spotify": "https://spotify/x"}},
            primary_country=Country.PE,
        )
        assert result.posted is False
        assert "challenge_required" in (result.failure_reason or "")
        assert account.status is InstagramAccountStatus.CHALLENGE

    async def test_story_failure_does_not_break_cycle(
        self,
        setup_orchestrator: dict[str, object],
    ) -> None:
        orchestrator: CrossPlatformSpilloverOrchestrator = setup_orchestrator[  # type: ignore[assignment]
            "orchestrator"
        ]
        instagram: AsyncMock = setup_orchestrator["instagram"]  # type: ignore[assignment]
        audio: Path = setup_orchestrator["audio"]  # type: ignore[assignment]
        instagram.post_story.side_effect = RuntimeError("story down")

        result = await orchestrator.run_cycle(
            artist=_artist(),
            track_uri="catalog:track:abc",
            track_title="t",
            artist_name="a",
            audio_track_path=audio,
            niche="lo-fi",
            target_dsps={Country.PE: {"spotify": "https://spotify/x"}},
            primary_country=Country.PE,
        )
        assert result.posted is True
