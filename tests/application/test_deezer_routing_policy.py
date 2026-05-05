"""Tests del `DeezerRoutingPolicy` y `SuperFanEligibilityService`.

Mockeamos `IDeezerClient` con `AsyncMock` para no tocar httpx.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from streaming_bot.application.deezer import (
    DeezerRoutingPolicy,
    RoutingReason,
    SuperFanEligibilityService,
)
from streaming_bot.domain.deezer import (
    DeezerListenerHistory,
    SuperFanProfile,
)


def _super_fan_history(account_id: str = "super-1") -> DeezerListenerHistory:
    return DeezerListenerHistory(
        account_id=account_id,
        artists_followed=tuple(f"artist-{i}" for i in range(60)),
        avg_session_minutes_30d=60.0,
        replay_rate=0.4,
        distinct_tracks_30d=300,
        distinct_albums_30d=40,
        last_session_at=datetime.now(UTC),
    )


def _pipeline_history(account_id: str = "pipeline-1") -> DeezerListenerHistory:
    """Cuenta cerca pero todavia no super-fan: faltan ~10 artistas y ~10min."""
    return DeezerListenerHistory(
        account_id=account_id,
        artists_followed=tuple(f"artist-{i}" for i in range(40)),
        avg_session_minutes_30d=35.0,
        replay_rate=0.35,
        distinct_tracks_30d=190,
        distinct_albums_30d=25,
    )


def _flat_history(account_id: str = "flat-1") -> DeezerListenerHistory:
    """Cuenta de spread plano: pocos plays, sin replay, bot-like."""
    return DeezerListenerHistory(
        account_id=account_id,
        artists_followed=tuple(f"artist-{i}" for i in range(5)),
        avg_session_minutes_30d=4.0,
        replay_rate=0.05,
        distinct_tracks_30d=10,
        distinct_albums_30d=2,
    )


class TestEligibilityService:
    async def test_super_fan_account_is_eligible(self) -> None:
        client = AsyncMock()
        client.get_user_history.return_value = _super_fan_history()
        service = SuperFanEligibilityService(deezer_client=client)
        assessment = await service.assess("super-1")
        assert assessment.is_eligible is True
        assert assessment.is_in_pipeline is False
        assert assessment.score is not None
        assert assessment.score.value == pytest.approx(1.0)
        assert assessment.rejection_reason is None

    async def test_pipeline_account_is_not_eligible_but_in_pipeline(self) -> None:
        client = AsyncMock()
        client.get_user_history.return_value = _pipeline_history()
        service = SuperFanEligibilityService(deezer_client=client)
        assessment = await service.assess("pipeline-1")
        assert assessment.is_eligible is False
        assert assessment.is_in_pipeline is True
        assert assessment.rejection_reason is None

    async def test_flat_account_rejected(self) -> None:
        client = AsyncMock()
        client.get_user_history.return_value = _flat_history()
        service = SuperFanEligibilityService(deezer_client=client)
        assessment = await service.assess("flat-1")
        assert assessment.is_eligible is False
        assert assessment.is_in_pipeline is False
        assert assessment.rejection_reason == "flat_spread_or_too_far_from_profile"

    async def test_no_history_short_circuits(self) -> None:
        client = AsyncMock()
        client.get_user_history.return_value = None
        service = SuperFanEligibilityService(deezer_client=client)
        assessment = await service.assess("ghost")
        assert assessment.is_eligible is False
        assert assessment.is_in_pipeline is False
        assert assessment.score is None
        assert assessment.rejection_reason == "no_history_available"

    async def test_is_eligible_helper(self) -> None:
        client = AsyncMock()
        client.get_user_history.return_value = _super_fan_history()
        service = SuperFanEligibilityService(deezer_client=client)
        assert await service.is_eligible("super-1") is True

    def test_lenient_profile_accepted(self) -> None:
        client = AsyncMock()
        service = SuperFanEligibilityService(
            deezer_client=client,
            profile=SuperFanProfile.lenient(),
        )
        assert service.profile.artists_followed_min == 25


class TestRoutingPolicy:
    async def test_select_returns_only_accepted_accounts(self) -> None:
        histories: dict[str, DeezerListenerHistory | None] = {
            "super-1": _super_fan_history("super-1"),
            "pipeline-1": _pipeline_history("pipeline-1"),
            "flat-1": _flat_history("flat-1"),
        }

        async def _fake_get(account_id: str) -> DeezerListenerHistory | None:
            return histories.get(account_id)

        client = AsyncMock()
        client.get_user_history.side_effect = _fake_get
        service = SuperFanEligibilityService(deezer_client=client)
        policy = DeezerRoutingPolicy(eligibility=service, max_routes=5)

        decisions = await policy.select_accounts_for_track(
            ["super-1", "pipeline-1", "flat-1"],
        )
        assert {d.account_id for d in decisions} == {"super-1", "pipeline-1"}
        # Super-fan debe estar primero (mayor score y prioridad).
        assert decisions[0].account_id == "super-1"
        assert decisions[0].reason == RoutingReason.SUPER_FAN
        assert decisions[1].reason == RoutingReason.PIPELINE

    async def test_evaluate_all_returns_full_diagnostics(self) -> None:
        histories: dict[str, DeezerListenerHistory | None] = {
            "super-1": _super_fan_history("super-1"),
            "flat-1": _flat_history("flat-1"),
            "ghost": None,
        }

        async def _fake_get(account_id: str) -> DeezerListenerHistory | None:
            return histories.get(account_id)

        client = AsyncMock()
        client.get_user_history.side_effect = _fake_get
        service = SuperFanEligibilityService(deezer_client=client)
        policy = DeezerRoutingPolicy(eligibility=service)

        decisions = await policy.evaluate_all(["super-1", "flat-1", "ghost"])
        reasons = {d.account_id: d.reason for d in decisions}
        assert reasons["super-1"] == RoutingReason.SUPER_FAN
        assert reasons["flat-1"] == RoutingReason.REJECTED_FLAT_SPREAD
        assert reasons["ghost"] == RoutingReason.NO_HISTORY

    async def test_max_routes_caps_results(self) -> None:
        # Tres super-fans validos.
        histories: dict[str, DeezerListenerHistory | None] = {
            f"super-{i}": _super_fan_history(f"super-{i}") for i in range(3)
        }

        async def _fake_get(account_id: str) -> DeezerListenerHistory | None:
            return histories.get(account_id)

        client = AsyncMock()
        client.get_user_history.side_effect = _fake_get
        service = SuperFanEligibilityService(deezer_client=client)
        policy = DeezerRoutingPolicy(eligibility=service, max_routes=2)

        decisions = await policy.select_accounts_for_track(list(histories.keys()))
        assert len(decisions) == 2

    async def test_accept_pipeline_false_filters_pipeline_accounts(self) -> None:
        client = AsyncMock()
        client.get_user_history.return_value = _pipeline_history()
        service = SuperFanEligibilityService(deezer_client=client)
        policy = DeezerRoutingPolicy(eligibility=service, accept_pipeline=False)
        decisions = await policy.select_accounts_for_track(["pipeline-1"])
        assert decisions == []

    async def test_empty_candidate_list_returns_empty(self) -> None:
        client = AsyncMock()
        service = SuperFanEligibilityService(deezer_client=client)
        policy = DeezerRoutingPolicy(eligibility=service)
        assert await policy.select_accounts_for_track([]) == []

    def test_invalid_max_routes_raises(self) -> None:
        client = AsyncMock()
        service = SuperFanEligibilityService(deezer_client=client)
        with pytest.raises(ValueError, match="max_routes"):
            DeezerRoutingPolicy(eligibility=service, max_routes=0)
