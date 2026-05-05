"""Tests de las politicas de delay de decision humana."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

import pytest

from streaming_bot.application.behavior.decision_delay import (
    DecisionType,
    DelayContext,
    LogNormalDelayPolicy,
    NullDelayPolicy,
    OpenAIDelayPolicy,
    build_default_delay_policy,
    now_local_hour,
)


class TestNullDelayPolicy:
    async def test_always_zero(self) -> None:
        policy = NullDelayPolicy()
        for kind in DecisionType:
            ms = await policy.decide(DelayContext(decision=kind))
            assert ms == 0


class TestLogNormalDelayPolicy:
    async def test_returns_non_negative(self) -> None:
        policy = LogNormalDelayPolicy(rng_seed=42)
        for kind in DecisionType:
            ms = await policy.decide(DelayContext(decision=kind))
            assert ms >= 0

    async def test_seed_reproducibility(self) -> None:
        a = LogNormalDelayPolicy(rng_seed=99)
        b = LogNormalDelayPolicy(rng_seed=99)
        ctx = DelayContext(decision=DecisionType.CLICK)
        results_a = [await a.decide(ctx) for _ in range(20)]
        results_b = [await b.decide(ctx) for _ in range(20)]
        assert results_a == results_b

    async def test_read_is_typically_slower_than_hover(self) -> None:
        """Promediando muchas muestras, READ debe ser claramente mayor que HOVER."""
        sample_size = 400
        policy_read = LogNormalDelayPolicy(rng_seed=1)
        read_samples = [
            await policy_read.decide(DelayContext(decision=DecisionType.READ))
            for _ in range(sample_size)
        ]
        policy_hover = LogNormalDelayPolicy(rng_seed=1)
        hover_samples = [
            await policy_hover.decide(DelayContext(decision=DecisionType.HOVER))
            for _ in range(sample_size)
        ]
        assert sum(read_samples) / sample_size > sum(hover_samples) / sample_size

    async def test_engagement_lurker_slower_than_fanatic(self) -> None:
        sample_size = 500
        ctx_lurker = DelayContext(decision=DecisionType.CLICK, engagement_level="lurker")
        ctx_fanatic = DelayContext(decision=DecisionType.CLICK, engagement_level="fanatic")
        lurker = LogNormalDelayPolicy(rng_seed=7)
        fanatic = LogNormalDelayPolicy(rng_seed=7)
        lurker_samples = [await lurker.decide(ctx_lurker) for _ in range(sample_size)]
        fanatic_samples = [await fanatic.decide(ctx_fanatic) for _ in range(sample_size)]
        assert sum(lurker_samples) / sample_size > sum(fanatic_samples) / sample_size

    async def test_late_night_is_slower(self) -> None:
        """Hora 03:00 debe penalizar el delay frente a media manana."""
        sample_size = 500
        morning = DelayContext(decision=DecisionType.CLICK, local_hour=10)
        late = DelayContext(decision=DecisionType.CLICK, local_hour=3)
        policy_a = LogNormalDelayPolicy(rng_seed=11)
        policy_b = LogNormalDelayPolicy(rng_seed=11)
        morning_samples = [await policy_a.decide(morning) for _ in range(sample_size)]
        late_samples = [await policy_b.decide(late) for _ in range(sample_size)]
        assert sum(late_samples) / sample_size > sum(morning_samples) / sample_size

    async def test_hard_cap_clamps_extreme_values(self) -> None:
        """Aun con seeds muy adversos, el delay no excede `hard_cap_ms`."""
        policy = LogNormalDelayPolicy(rng_seed=2026, hard_cap_ms=500)
        for _ in range(200):
            ms = await policy.decide(DelayContext(decision=DecisionType.READ))
            assert ms <= 500

    async def test_unknown_engagement_uses_default_factor(self) -> None:
        policy = LogNormalDelayPolicy(rng_seed=33)
        ctx = DelayContext(decision=DecisionType.CLICK, engagement_level="unknown_level")
        ms = await policy.decide(ctx)
        assert ms >= 0


class TestOpenAIDelayPolicy:
    async def test_uses_llm_when_available(self) -> None:
        async def fake_llm(prompt: str) -> str:
            assert "click" in prompt
            return "1234"

        fallback = LogNormalDelayPolicy(rng_seed=1)
        policy = OpenAIDelayPolicy(fallback=fallback, llm_callable=fake_llm)
        ms = await policy.decide(DelayContext(decision=DecisionType.CLICK))
        assert ms == 1234

    async def test_falls_back_when_llm_raises(self) -> None:
        async def broken(prompt: str) -> str:
            _ = prompt
            raise RuntimeError("boom")

        fallback = LogNormalDelayPolicy(rng_seed=1)
        policy = OpenAIDelayPolicy(fallback=fallback, llm_callable=broken)
        ms = await policy.decide(DelayContext(decision=DecisionType.CLICK))
        # Cae al fallback log-normal; no rompe la sesion.
        assert ms >= 0

    async def test_falls_back_when_llm_returns_garbage(self) -> None:
        async def noise(prompt: str) -> str:
            _ = prompt
            return "hola que tal"

        fallback = LogNormalDelayPolicy(rng_seed=2)
        policy = OpenAIDelayPolicy(fallback=fallback, llm_callable=noise)
        ms = await policy.decide(DelayContext(decision=DecisionType.READ))
        assert ms >= 0

    async def test_negative_llm_is_clamped_to_zero(self) -> None:
        async def negative(prompt: str) -> str:
            _ = prompt
            return "-500"

        fallback = LogNormalDelayPolicy(rng_seed=3)
        policy = OpenAIDelayPolicy(fallback=fallback, llm_callable=negative)
        ms = await policy.decide(DelayContext(decision=DecisionType.HOVER))
        assert ms == 0

    async def test_huge_llm_is_clamped_to_cap(self) -> None:
        async def huge(prompt: str) -> str:
            _ = prompt
            return "9999999"

        fallback = LogNormalDelayPolicy(rng_seed=4)
        policy = OpenAIDelayPolicy(
            fallback=fallback,
            llm_callable=huge,
            cap_ms=2_000,
        )
        ms = await policy.decide(DelayContext(decision=DecisionType.NAVIGATE))
        assert ms == 2_000


class TestBuilder:
    def test_returns_log_normal_when_no_env_key(self) -> None:
        policy = build_default_delay_policy(env={})
        assert isinstance(policy, LogNormalDelayPolicy)

    def test_returns_log_normal_when_no_callable(self) -> None:
        policy = build_default_delay_policy(env={"OPENAI_API_KEY": "sk-test"})
        assert isinstance(policy, LogNormalDelayPolicy)

    def test_returns_openai_when_env_and_callable_set(self) -> None:
        async def stub(prompt: str) -> str:
            _ = prompt
            return "100"

        policy = build_default_delay_policy(
            env={"OPENAI_API_KEY": "sk-test"},
            llm_callable=cast(Callable[[str], object], stub),  # type: ignore[arg-type]
        )
        assert isinstance(policy, OpenAIDelayPolicy)


class TestNowLocalHour:
    def test_no_offset_returns_utc_hour(self) -> None:
        assert now_local_hour(datetime(2026, 1, 1, 13, 0, tzinfo=UTC)) == 13

    def test_offset_wraps_correctly(self) -> None:
        assert now_local_hour(datetime(2026, 1, 1, 23, 0, tzinfo=UTC), 2) == 1
        assert now_local_hour(datetime(2026, 1, 1, 1, 0, tzinfo=UTC), -3) == 22


@pytest.mark.parametrize("kind", list(DecisionType))
async def test_log_normal_supports_every_decision_type(kind: DecisionType) -> None:
    """Garantiza que cada tipo enumerado tiene parametros calibrados."""
    policy = LogNormalDelayPolicy(rng_seed=0)
    ms = await policy.decide(DelayContext(decision=kind))
    assert ms >= 0
