"""Tests unitarios de `PremierEligibility` (modelo) + monetizable territories."""

from __future__ import annotations

import pytest

from streaming_bot.domain.soundcloud.models import (
    DEFAULT_PREMIER_FOLLOWER_THRESHOLD,
    DEFAULT_PREMIER_PLAYS_THRESHOLD,
    PremierEligibility,
)
from streaming_bot.domain.soundcloud.monetizable_territories import (
    MONETIZABLE_TERRITORIES,
    is_monetizable,
)
from streaming_bot.domain.value_objects import Country


class TestPremierEligibility:
    def test_eligible_when_both_thresholds_met(self) -> None:
        eligibility = PremierEligibility(
            track_urn="soundcloud:tracks:1",
            followers=1500,
            monetizable_plays_30d=2000,
        )
        assert eligibility.is_eligible
        assert eligibility.gap_followers == 0
        assert eligibility.gap_monetizable_plays == 0

    def test_not_eligible_when_followers_short(self) -> None:
        eligibility = PremierEligibility(
            track_urn="soundcloud:tracks:1",
            followers=400,
            monetizable_plays_30d=2000,
        )
        assert not eligibility.is_eligible
        assert eligibility.gap_followers == 600
        assert eligibility.gap_monetizable_plays == 0

    def test_not_eligible_when_plays_short(self) -> None:
        eligibility = PremierEligibility(
            track_urn="soundcloud:tracks:1",
            followers=1500,
            monetizable_plays_30d=300,
        )
        assert not eligibility.is_eligible
        assert eligibility.gap_followers == 0
        assert eligibility.gap_monetizable_plays == 700

    def test_gap_never_negative(self) -> None:
        eligibility = PremierEligibility(
            track_urn="soundcloud:tracks:1",
            followers=5000,
            monetizable_plays_30d=10000,
        )
        assert eligibility.gap_followers == 0
        assert eligibility.gap_monetizable_plays == 0

    def test_thresholds_default_to_q1_2026(self) -> None:
        eligibility = PremierEligibility(
            track_urn="soundcloud:tracks:1",
            followers=0,
            monetizable_plays_30d=0,
        )
        assert eligibility.threshold_followers == DEFAULT_PREMIER_FOLLOWER_THRESHOLD
        assert eligibility.threshold_plays == DEFAULT_PREMIER_PLAYS_THRESHOLD
        assert eligibility.gap_followers == DEFAULT_PREMIER_FOLLOWER_THRESHOLD
        assert eligibility.gap_monetizable_plays == DEFAULT_PREMIER_PLAYS_THRESHOLD

    def test_custom_thresholds_are_respected(self) -> None:
        eligibility = PremierEligibility(
            track_urn="soundcloud:tracks:1",
            followers=200,
            monetizable_plays_30d=300,
            threshold_followers=500,
            threshold_plays=500,
        )
        assert eligibility.gap_followers == 300
        assert eligibility.gap_monetizable_plays == 200

    def test_negative_followers_raises(self) -> None:
        with pytest.raises(ValueError, match="followers"):
            PremierEligibility(
                track_urn="soundcloud:tracks:1",
                followers=-5,
                monetizable_plays_30d=0,
            )

    def test_negative_plays_raises(self) -> None:
        with pytest.raises(ValueError, match="monetizable_plays_30d"):
            PremierEligibility(
                track_urn="soundcloud:tracks:1",
                followers=0,
                monetizable_plays_30d=-10,
            )

    def test_zero_threshold_followers_raises(self) -> None:
        with pytest.raises(ValueError, match="threshold_followers"):
            PremierEligibility(
                track_urn="soundcloud:tracks:1",
                followers=0,
                monetizable_plays_30d=0,
                threshold_followers=0,
            )

    def test_zero_threshold_plays_raises(self) -> None:
        with pytest.raises(ValueError, match="threshold_plays"):
            PremierEligibility(
                track_urn="soundcloud:tracks:1",
                followers=0,
                monetizable_plays_30d=0,
                threshold_plays=0,
            )


class TestMonetizableTerritories:
    def test_us_uk_ca_au_nz_are_monetizable(self) -> None:
        for country in (Country.US, Country.GB, Country.CA, Country.AU, Country.NZ):
            assert is_monetizable(country), country

    def test_nordics_are_monetizable(self) -> None:
        for country in (Country.SE, Country.NO, Country.DK, Country.FI):
            assert is_monetizable(country)

    def test_eu_tier1_is_monetizable(self) -> None:
        for country in (Country.IE, Country.DE, Country.FR, Country.NL):
            assert is_monetizable(country)

    def test_latam_is_not_monetizable(self) -> None:
        for country in (Country.PE, Country.MX, Country.CL, Country.AR, Country.CO):
            assert not is_monetizable(country)

    def test_set_is_frozen(self) -> None:
        # frozenset es inmutable: confirmamos el contrato.
        assert isinstance(MONETIZABLE_TERRITORIES, frozenset)
        with pytest.raises(AttributeError):
            MONETIZABLE_TERRITORIES.add(Country.PE)  # type: ignore[attr-defined]
