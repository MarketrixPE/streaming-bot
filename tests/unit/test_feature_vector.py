"""Tests del VO ``AccountFeatureVector``."""

from __future__ import annotations

import pytest

from streaming_bot.domain.ml.feature_vector import (
    FEATURE_NAMES,
    AccountFeatureVector,
)


def _build_full_kwargs(**overrides: float) -> dict[str, float]:
    """Construye un diccionario válido para ``AccountFeatureVector``."""
    base: dict[str, float] = {
        "streams_24h": 50.0,
        "streams_7d": 350.0,
        "save_rate_24h": 0.05,
        "skip_rate_24h": 0.2,
        "queue_rate_24h": 0.1,
        "ip_diversity_24h": 2.0,
        "fingerprint_age_days": 30.0,
        "distinct_dsps_24h": 1.0,
        "hour_of_day_consistency": 0.8,
        "geo_consistency_score": 0.95,
        "captcha_encounters_24h": 0.0,
        "failed_streams_24h": 1.0,
        "partial_streams_24h": 5.0,
        "completion_rate_24h": 0.85,
        "sessions_24h": 6.0,
        "avg_session_duration_minutes": 45.0,
        "distinct_artists_24h": 12.0,
        "distinct_tracks_24h": 30.0,
        "repeat_track_ratio_24h": 0.4,
        "night_streams_ratio_24h": 0.1,
        "rapid_skip_ratio_24h": 0.05,
        "country_changes_24h": 1.0,
        "user_agent_changes_7d": 1.0,
        "previous_quarantine_count_30d": 0.0,
    }
    base.update(overrides)
    return base


class TestConstruction:
    def test_valid_vector(self) -> None:
        vector = AccountFeatureVector(account_id="acc-1", **_build_full_kwargs())
        assert vector.account_id == "acc-1"
        assert vector.streams_24h == 50.0

    def test_as_array_respects_canonical_order(self) -> None:
        vector = AccountFeatureVector(account_id="acc-1", **_build_full_kwargs())
        arr = vector.as_array()
        assert len(arr) == len(FEATURE_NAMES)
        assert all(isinstance(v, float) for v in arr)
        for idx, name in enumerate(FEATURE_NAMES):
            assert arr[idx] == float(getattr(vector, name))


class TestValidation:
    @pytest.mark.parametrize(
        "field",
        [
            "save_rate_24h",
            "skip_rate_24h",
            "completion_rate_24h",
            "geo_consistency_score",
            "rapid_skip_ratio_24h",
        ],
    )
    def test_ratio_must_be_between_0_and_1(self, field: str) -> None:
        kwargs = _build_full_kwargs(**{field: 1.5})
        with pytest.raises(ValueError, match=f"{field} fuera de rango"):
            AccountFeatureVector(account_id="acc-1", **kwargs)

    @pytest.mark.parametrize(
        "field",
        [
            "streams_24h",
            "streams_7d",
            "captcha_encounters_24h",
            "fingerprint_age_days",
        ],
    )
    def test_count_cannot_be_negative(self, field: str) -> None:
        kwargs = _build_full_kwargs(**{field: -1.0})
        with pytest.raises(ValueError, match=f"{field} no puede ser negativo"):
            AccountFeatureVector(account_id="acc-1", **kwargs)


class TestFromDict:
    def test_missing_features_default_to_zero(self) -> None:
        vector = AccountFeatureVector.from_dict(
            account_id="acc-1",
            values={"streams_24h": 10.0, "save_rate_24h": 0.1},
        )
        assert vector.streams_24h == 10.0
        assert vector.streams_7d == 0.0
        assert vector.completion_rate_24h == 0.0

    def test_extra_keys_are_ignored(self) -> None:
        values = _build_full_kwargs()
        values["unknown_extra"] = 99.0
        vector = AccountFeatureVector.from_dict(account_id="acc-1", values=values)
        assert vector.streams_24h == 50.0


class TestImmutability:
    def test_frozen(self) -> None:
        vector = AccountFeatureVector(account_id="acc-1", **_build_full_kwargs())
        with pytest.raises(AttributeError):
            vector.streams_24h = 99.0  # type: ignore[misc]
