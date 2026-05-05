"""Tests del PremierEligibilityService + PremierBoostStrategy."""

from __future__ import annotations

from unittest.mock import AsyncMock

from streaming_bot.application.soundcloud.premier_eligibility_service import (
    PremierEligibilityService,
)
from streaming_bot.application.soundcloud.premier_strategy import (
    PremierBoostStrategy,
    PremierBoostType,
)
from streaming_bot.domain.entities import Account
from streaming_bot.domain.soundcloud.models import (
    PremierEligibility,
    SoundcloudTrack,
    SoundcloudUser,
)
from streaming_bot.domain.value_objects import Country


def _account(country: Country, idx: int = 0) -> Account:
    return Account.new(
        username=f"u{idx}@sc",
        password="pw",
        country=country,
    )


class TestPremierEligibilityService:
    async def test_evaluate_returns_none_when_track_missing(self) -> None:
        client = AsyncMock()
        client.get_track.return_value = None
        provider = AsyncMock(return_value=0)
        service = PremierEligibilityService(
            client=client,
            monetizable_plays_provider=provider,
        )

        result = await service.evaluate(123)

        assert result is None
        client.get_user.assert_not_awaited()
        provider.assert_not_awaited()

    async def test_evaluate_returns_none_when_user_missing(self) -> None:
        client = AsyncMock()
        client.get_track.return_value = SoundcloudTrack(
            urn="soundcloud:tracks:1",
            track_id=1,
            title="t",
            permalink_url="https://soundcloud.com/x/t",
            duration_ms=180_000,
            user_id=42,
            playback_count=500,
        )
        client.get_user.return_value = None
        provider = AsyncMock(return_value=400)
        service = PremierEligibilityService(
            client=client,
            monetizable_plays_provider=provider,
        )

        result = await service.evaluate("soundcloud:tracks:1")

        assert result is None
        provider.assert_not_awaited()

    async def test_evaluate_returns_eligibility_with_gaps(self) -> None:
        client = AsyncMock()
        client.get_track.return_value = SoundcloudTrack(
            urn="soundcloud:tracks:9",
            track_id=9,
            title="t",
            permalink_url="https://soundcloud.com/x/t",
            duration_ms=180_000,
            user_id=1,
            playback_count=12_345,
        )
        client.get_user.return_value = SoundcloudUser(
            user_id=1,
            permalink="x",
            username="x",
            followers_count=320,
        )
        provider = AsyncMock(return_value=450)
        service = PremierEligibilityService(
            client=client,
            monetizable_plays_provider=provider,
        )

        result = await service.evaluate(9)

        assert result is not None
        assert result.track_urn == "soundcloud:tracks:9"
        assert result.followers == 320
        assert result.monetizable_plays_30d == 450
        assert result.gap_followers == 680
        assert result.gap_monetizable_plays == 550
        assert not result.is_eligible

    async def test_evaluate_returns_eligible_when_thresholds_met(self) -> None:
        client = AsyncMock()
        client.get_track.return_value = SoundcloudTrack(
            urn="soundcloud:tracks:9",
            track_id=9,
            title="t",
            permalink_url="https://x",
            duration_ms=1,
            user_id=2,
            playback_count=10_000,
        )
        client.get_user.return_value = SoundcloudUser(
            user_id=2,
            permalink="x",
            username="x",
            followers_count=2_000,
        )
        provider = AsyncMock(return_value=2_500)
        service = PremierEligibilityService(
            client=client,
            monetizable_plays_provider=provider,
        )

        result = await service.evaluate(9)

        assert result is not None
        assert result.is_eligible


class TestPremierBoostStrategy:
    def test_returns_empty_plan_when_already_eligible(self) -> None:
        eligibility = PremierEligibility(
            track_urn="soundcloud:tracks:7",
            followers=1500,
            monetizable_plays_30d=2_000,
        )
        strategy = PremierBoostStrategy(rng_seed=1)

        plan = strategy.plan(
            eligibility=eligibility,
            accounts_pool=[_account(Country.US, 1)],
        )

        assert plan.total_actions == 0
        assert plan.gap_followers == 0
        assert plan.gap_monetizable_plays == 0

    def test_assigns_plays_only_from_monetizable_pool(self) -> None:
        eligibility = PremierEligibility(
            track_urn="soundcloud:tracks:7",
            followers=2_000,  # gap_followers=0
            monetizable_plays_30d=997,  # gap_plays=3
        )
        accounts = [
            _account(Country.PE, 1),  # no monetizable
            _account(Country.US, 2),
            _account(Country.PE, 3),
            _account(Country.GB, 4),
            _account(Country.CA, 5),
            _account(Country.MX, 6),
        ]
        strategy = PremierBoostStrategy(
            min_jitter_ms=100,
            max_jitter_ms=100,
            rng_seed=42,
        )

        plan = strategy.plan(eligibility=eligibility, accounts_pool=accounts)

        play_actions = [a for a in plan.actions if a.action is PremierBoostType.PLAY]
        assert len(play_actions) == 3
        for action in play_actions:
            assert action.monetizable
            assert action.country in {"US", "GB", "CA"}
        assert plan.follow_actions == 0

    def test_assigns_follows_after_plays(self) -> None:
        eligibility = PremierEligibility(
            track_urn="soundcloud:tracks:7",
            followers=998,  # gap_followers=2
            monetizable_plays_30d=999,  # gap_plays=1
        )
        accounts = [
            _account(Country.US, 1),
            _account(Country.GB, 2),
            _account(Country.PE, 3),
        ]
        strategy = PremierBoostStrategy(
            min_jitter_ms=10,
            max_jitter_ms=10,
            rng_seed=7,
        )

        plan = strategy.plan(eligibility=eligibility, accounts_pool=accounts)

        play_actions = [a for a in plan.actions if a.action is PremierBoostType.PLAY]
        follow_actions = [a for a in plan.actions if a.action is PremierBoostType.FOLLOW]
        assert len(play_actions) == 1
        assert len(follow_actions) == 2
        # Plays uses monetizable account first; follows can include non-monetizable.
        assert play_actions[0].monetizable
        countries_used = {a.country for a in plan.actions}
        # Both monetizables y la PE (no monetizable) deberian aparecer.
        assert "US" in countries_used
        assert "GB" in countries_used
        assert "PE" in countries_used

    def test_skips_unusable_accounts(self) -> None:
        usable = _account(Country.US, 1)
        banned = _account(Country.GB, 2)
        banned.deactivate("test")

        eligibility = PremierEligibility(
            track_urn="soundcloud:tracks:7",
            followers=999,
            monetizable_plays_30d=999,
        )
        strategy = PremierBoostStrategy(rng_seed=3)

        plan = strategy.plan(
            eligibility=eligibility,
            accounts_pool=[banned, usable],
        )

        used_ids = {a.account_id for a in plan.actions}
        assert banned.id not in used_ids
        assert usable.id in used_ids

    def test_jitter_is_within_bounds(self) -> None:
        eligibility = PremierEligibility(
            track_urn="soundcloud:tracks:7",
            followers=995,
            monetizable_plays_30d=995,
        )
        accounts = [_account(Country.US, i) for i in range(10)]
        strategy = PremierBoostStrategy(
            min_jitter_ms=500,
            max_jitter_ms=2_500,
            rng_seed=99,
        )

        plan = strategy.plan(eligibility=eligibility, accounts_pool=accounts)

        for action in plan.actions:
            assert 500 <= action.delay_ms <= 2_500

    def test_deterministic_with_seed(self) -> None:
        eligibility = PremierEligibility(
            track_urn="soundcloud:tracks:7",
            followers=995,
            monetizable_plays_30d=995,
        )
        accounts = [_account(Country.US, i) for i in range(8)]

        plan_a = PremierBoostStrategy(
            min_jitter_ms=10,
            max_jitter_ms=2_000,
            rng_seed=12345,
        ).plan(eligibility=eligibility, accounts_pool=accounts)
        plan_b = PremierBoostStrategy(
            min_jitter_ms=10,
            max_jitter_ms=2_000,
            rng_seed=12345,
        ).plan(eligibility=eligibility, accounts_pool=accounts)

        assert plan_a.actions == plan_b.actions
