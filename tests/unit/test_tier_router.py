"""Tests del MultiTierGeoRouter (reglas de tier + RoutingPolicy)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import structlog

from streaming_bot.application.routing import policy as policy_module
from streaming_bot.application.routing.policy import RoutingPolicy
from streaming_bot.application.routing.tier_router import MultiTierGeoRouter
from streaming_bot.domain.routing.tier import TIER_TO_COUNTRIES, Tier
from streaming_bot.domain.routing.track_health import TrackHealthScore
from streaming_bot.domain.song import Song, SongMetadata, SongRole, SongTier
from streaming_bot.domain.value_objects import Country


def _song(*, tier: SongTier = SongTier.MID, uri: str = "spotify:track:abc") -> Song:
    """Helper para construir una Song minima de pruebas."""
    return Song(
        spotify_uri=uri,
        title="t",
        artist_name="x",
        artist_uri="spotify:artist:y",
        role=SongRole.TARGET,
        metadata=SongMetadata(duration_seconds=180),
        tier=tier,
    )


def _score(
    *,
    age_days: int = 30,
    plays_30d: int = 1000,
    save_rate: float = 0.03,
    skip_rate: float = 0.30,
    saturation: float = 0.0,
) -> TrackHealthScore:
    return TrackHealthScore(
        age_days=age_days,
        plays_30d=plays_30d,
        save_rate=save_rate,
        skip_rate=skip_rate,
        saturation_score=saturation,
        computed_at=datetime(2026, 5, 4, tzinfo=UTC),
    )


class TestPickTier:
    def test_new_track_goes_to_tier_3(self) -> None:
        router = MultiTierGeoRouter()
        assert (
            router.pick_tier(track=_song(), score=_score(age_days=3)) == Tier.TIER_3
        )

    def test_new_track_with_high_saturation_still_tier_3(self) -> None:
        router = MultiTierGeoRouter()
        assert (
            router.pick_tier(
                track=_song(),
                score=_score(age_days=2, saturation=0.95),
            )
            == Tier.TIER_3
        )

    def test_age_at_threshold_no_longer_new(self) -> None:
        router = MultiTierGeoRouter()
        result = router.pick_tier(
            track=_song(),
            score=_score(age_days=7, save_rate=0.01, skip_rate=0.5),
        )
        assert result == Tier.TIER_2

    def test_high_save_low_skip_goes_to_tier_1(self) -> None:
        router = MultiTierGeoRouter()
        score = _score(age_days=30, save_rate=0.05, skip_rate=0.40)
        assert router.pick_tier(track=_song(), score=score) == Tier.TIER_1

    def test_save_rate_at_min_qualifies_for_tier_1(self) -> None:
        router = MultiTierGeoRouter()
        score = _score(save_rate=0.04, skip_rate=0.30)
        assert router.pick_tier(track=_song(), score=score) == Tier.TIER_1

    def test_skip_rate_at_max_disqualifies_tier_1(self) -> None:
        router = MultiTierGeoRouter()
        score = _score(save_rate=0.05, skip_rate=0.45)
        assert router.pick_tier(track=_song(), score=score) == Tier.TIER_2

    def test_high_save_but_high_skip_falls_to_tier_2(self) -> None:
        router = MultiTierGeoRouter()
        score = _score(age_days=30, save_rate=0.05, skip_rate=0.46)
        assert router.pick_tier(track=_song(), score=score) == Tier.TIER_2

    def test_default_is_tier_2(self) -> None:
        router = MultiTierGeoRouter()
        score = _score(age_days=30, save_rate=0.02, skip_rate=0.30)
        assert router.pick_tier(track=_song(), score=score) == Tier.TIER_2

    def test_degraded_high_volume_low_save_to_tier_3(self) -> None:
        router = MultiTierGeoRouter()
        score = _score(
            age_days=120,
            plays_30d=80_000,
            save_rate=0.01,
            skip_rate=0.30,
        )
        assert router.pick_tier(track=_song(), score=score) == Tier.TIER_3

    def test_degrade_only_volume_no_low_save_does_not_apply(self) -> None:
        router = MultiTierGeoRouter()
        score = _score(plays_30d=80_000, save_rate=0.05, skip_rate=0.30)
        assert router.pick_tier(track=_song(), score=score) == Tier.TIER_1

    def test_degrade_only_low_save_no_volume_does_not_apply(self) -> None:
        router = MultiTierGeoRouter()
        score = _score(plays_30d=10_000, save_rate=0.01, skip_rate=0.30)
        assert router.pick_tier(track=_song(), score=score) == Tier.TIER_2

    def test_saturation_rotates_tier_1_to_tier_2(self) -> None:
        router = MultiTierGeoRouter()
        score = _score(
            age_days=60,
            save_rate=0.06,
            skip_rate=0.30,
            saturation=0.95,
        )
        assert router.pick_tier(track=_song(), score=score) == Tier.TIER_2

    def test_saturation_rotates_tier_2_to_tier_3(self) -> None:
        router = MultiTierGeoRouter()
        score = _score(
            age_days=60,
            save_rate=0.02,
            skip_rate=0.30,
            saturation=0.85,
        )
        assert router.pick_tier(track=_song(), score=score) == Tier.TIER_3

    def test_saturation_at_threshold_does_not_rotate(self) -> None:
        router = MultiTierGeoRouter()
        score = _score(
            age_days=60,
            save_rate=0.05,
            skip_rate=0.30,
            saturation=0.80,
        )
        assert router.pick_tier(track=_song(), score=score) == Tier.TIER_1

    def test_custom_policy_lower_save_rate_threshold(self) -> None:
        policy = RoutingPolicy(tier1_save_rate_min=0.02)
        router = MultiTierGeoRouter(policy=policy)
        score = _score(save_rate=0.025, skip_rate=0.30)
        assert router.pick_tier(track=_song(), score=score) == Tier.TIER_1

    def test_policy_property_exposes_policy(self) -> None:
        policy = RoutingPolicy(new_track_age_days=14)
        router = MultiTierGeoRouter(policy=policy)
        assert router.policy is policy

    def test_logger_is_invoked_when_provided(self) -> None:
        # Verifica que el path con logger no rompe (cubre la rama bind+debug).
        log = structlog.get_logger().bind()
        router = MultiTierGeoRouter(logger=log)
        result = router.pick_tier(track=_song(), score=_score(age_days=2))
        assert result == Tier.TIER_3


class TestTierToCountriesMapping:
    def test_no_country_in_two_tiers(self) -> None:
        seen: set[Country] = set()
        for members in TIER_TO_COUNTRIES.values():
            assert seen.isdisjoint(members), "pais en dos tiers"
            seen |= members

    def test_tier_1_includes_anglo_and_nordic(self) -> None:
        tier1 = TIER_TO_COUNTRIES[Tier.TIER_1]
        assert {Country.US, Country.GB, Country.AU, Country.SE, Country.NO}.issubset(
            tier1
        )

    def test_tier_2_includes_eu_premium_and_latam_premium(self) -> None:
        tier2 = TIER_TO_COUNTRIES[Tier.TIER_2]
        assert {Country.DE, Country.FR, Country.ES, Country.MX, Country.PE}.issubset(
            tier2
        )

    def test_tier_3_includes_br_and_high_volume(self) -> None:
        tier3 = TIER_TO_COUNTRIES[Tier.TIER_3]
        assert Country.BR in tier3
        assert Country.TH in tier3


class TestRoutingPolicy:
    def test_invalid_age_raises(self) -> None:
        with pytest.raises(ValueError, match="new_track_age_days"):
            RoutingPolicy(new_track_age_days=-1)

    def test_invalid_save_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="tier1_save_rate"):
            RoutingPolicy(tier1_save_rate_min=2.0)

    def test_invalid_skip_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="tier1_skip_rate"):
            RoutingPolicy(tier1_skip_rate_max=-0.1)

    def test_invalid_saturation_raises(self) -> None:
        with pytest.raises(ValueError, match="saturation_threshold"):
            RoutingPolicy(saturation_threshold=0.0)

    def test_invalid_degrade_plays_raises(self) -> None:
        with pytest.raises(ValueError, match="degrade_plays_30d"):
            RoutingPolicy(degrade_plays_30d=-1)

    def test_invalid_degrade_save_raises(self) -> None:
        with pytest.raises(ValueError, match="degrade_save_rate_max"):
            RoutingPolicy(degrade_save_rate_max=2.0)

    def test_invalid_max_safe_raises(self) -> None:
        with pytest.raises(ValueError, match="max_safe"):
            RoutingPolicy(max_safe_streams_24h_by_tier={Tier.TIER_1: 0})

    def test_tier_for_country_resolves(self) -> None:
        policy = RoutingPolicy()
        assert policy.tier_for_country(Country.US) == Tier.TIER_1
        assert policy.tier_for_country(Country.MX) == Tier.TIER_2
        assert policy.tier_for_country(Country.BR) == Tier.TIER_3

    def test_tier_for_country_unknown_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Restringimos temporalmente el mapping para forzar el path "no encontrado".
        monkeypatch.setattr(
            policy_module,
            "TIER_TO_COUNTRIES",
            {Tier.TIER_1: frozenset({Country.US})},
        )
        assert RoutingPolicy().tier_for_country(Country.BR) is None

    def test_max_safe_streams_24h_returns_configured(self) -> None:
        policy = RoutingPolicy()
        assert policy.max_safe_streams_24h(Tier.TIER_1) == 1500
        assert policy.max_safe_streams_24h(Tier.TIER_2) == 3500
        assert policy.max_safe_streams_24h(Tier.TIER_3) == 9000

    def test_max_safe_streams_24h_missing_raises(self) -> None:
        policy = RoutingPolicy(
            max_safe_streams_24h_by_tier={Tier.TIER_1: 1000, Tier.TIER_2: 2000}
        )
        with pytest.raises(KeyError, match="max_safe"):
            policy.max_safe_streams_24h(Tier.TIER_3)

    def test_next_less_saturated_chain(self) -> None:
        policy = RoutingPolicy()
        assert policy.next_less_saturated_tier(Tier.TIER_1) == Tier.TIER_2
        assert policy.next_less_saturated_tier(Tier.TIER_2) == Tier.TIER_3
        assert policy.next_less_saturated_tier(Tier.TIER_3) == Tier.TIER_3
