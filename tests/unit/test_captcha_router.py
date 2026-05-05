"""Tests del CaptchaSolverRouter (failover ordenado + budget guard)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from streaming_bot.domain.ports.captcha_solver import (
    CaptchaSolverError,
    ICaptchaSolver,
)
from streaming_bot.infrastructure.captcha.budget_guard import BudgetGuard
from streaming_bot.infrastructure.captcha.captcha_router import (
    CaptchaCostTable,
    CaptchaSolverRouter,
)


class _FakeSolver(ICaptchaSolver):
    """Solver fake configurable: cada metodo puede devolver token, lanzar
    CaptchaSolverError o NotImplementedError. Cuenta llamadas."""

    def __init__(
        self,
        *,
        recaptcha_v2_result: str | Exception | None = None,
        recaptcha_v3_result: str | Exception | None = None,
        hcaptcha_result: str | Exception | None = None,
        turnstile_result: str | Exception | None = None,
        image_result: str | Exception | None = None,
    ) -> None:
        self._results: dict[str, str | Exception | None] = {
            "solve_recaptcha_v2": recaptcha_v2_result,
            "solve_recaptcha_v3": recaptcha_v3_result,
            "solve_hcaptcha": hcaptcha_result,
            "solve_cloudflare_turnstile": turnstile_result,
            "solve_image_text": image_result,
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _resolve(self, method: str, kwargs: dict[str, Any]) -> str:
        self.calls.append((method, kwargs))
        result = self._results[method]
        if isinstance(result, Exception):
            raise result
        if result is None:
            raise CaptchaSolverError(f"fake: {method} no configurado")
        return result

    async def solve_recaptcha_v2(self, *, site_key: str, page_url: str) -> str:
        return self._resolve("solve_recaptcha_v2", {"site_key": site_key, "page_url": page_url})

    async def solve_recaptcha_v3(
        self,
        *,
        site_key: str,
        page_url: str,
        action: str,
        min_score: float,
    ) -> str:
        return self._resolve(
            "solve_recaptcha_v3",
            {
                "site_key": site_key,
                "page_url": page_url,
                "action": action,
                "min_score": min_score,
            },
        )

    async def solve_hcaptcha(self, *, site_key: str, page_url: str) -> str:
        return self._resolve("solve_hcaptcha", {"site_key": site_key, "page_url": page_url})

    async def solve_cloudflare_turnstile(self, *, site_key: str, page_url: str) -> str:
        return self._resolve(
            "solve_cloudflare_turnstile",
            {"site_key": site_key, "page_url": page_url},
        )

    async def solve_image_text(self, *, image_b64: str, hint: str) -> str:
        return self._resolve(
            "solve_image_text",
            {"image_b64": image_b64, "hint": hint},
        )


def _build_router(
    providers: Sequence[tuple[str, ICaptchaSolver]],
    *,
    cap_cents: float = 100.0,
) -> tuple[CaptchaSolverRouter, BudgetGuard]:
    guard = BudgetGuard(daily_cap_cents=cap_cents)
    router = CaptchaSolverRouter(providers=providers, budget_guard=guard)
    return router, guard


class TestCaptchaSolverRouter:
    async def test_first_provider_wins(self) -> None:
        primary = _FakeSolver(recaptcha_v2_result="TOKEN_PRIMARY")
        backup = _FakeSolver(recaptcha_v2_result="TOKEN_BACKUP")
        router, guard = _build_router(
            [("capsolver", primary), ("twocaptcha", backup)],
        )

        token = await router.solve_recaptcha_v2(
            site_key="x",
            page_url="https://example.com",
        )

        assert token == "TOKEN_PRIMARY"
        assert primary.calls == [
            ("solve_recaptcha_v2", {"site_key": "x", "page_url": "https://example.com"}),
        ]
        assert backup.calls == []
        assert guard.total_spent_cents == pytest.approx(0.08)
        assert router.total_spent_cents == pytest.approx(0.08)

    async def test_failover_to_secondary_on_error(self) -> None:
        primary = _FakeSolver(
            recaptcha_v2_result=CaptchaSolverError("capsolver: out of balance"),
        )
        backup = _FakeSolver(recaptcha_v2_result="TOKEN_BACKUP")
        router, guard = _build_router(
            [("capsolver", primary), ("twocaptcha", backup)],
        )

        token = await router.solve_recaptcha_v2(
            site_key="x",
            page_url="https://example.com",
        )

        assert token == "TOKEN_BACKUP"
        assert len(primary.calls) == 1
        assert len(backup.calls) == 1
        assert guard.total_spent_cents == pytest.approx(0.088)

    async def test_all_providers_fail_raises_with_chain(self) -> None:
        primary = _FakeSolver(
            recaptcha_v2_result=CaptchaSolverError("capsolver fallo"),
        )
        backup = _FakeSolver(
            recaptcha_v2_result=CaptchaSolverError("twocaptcha fallo"),
        )
        router, guard = _build_router(
            [("capsolver", primary), ("twocaptcha", backup)],
        )

        with pytest.raises(CaptchaSolverError) as excinfo:
            await router.solve_recaptcha_v2(
                site_key="x",
                page_url="https://example.com",
            )

        message = str(excinfo.value)
        assert "capsolver fallo" in message
        assert "twocaptcha fallo" in message
        assert guard.total_spent_cents == pytest.approx(0.0)

    async def test_not_implemented_skips_without_charging(self) -> None:
        primary = _FakeSolver(
            recaptcha_v2_result=CaptchaSolverError("capsolver fallo"),
        )
        gpt = _FakeSolver(recaptcha_v2_result=NotImplementedError("no soportado"))
        backup = _FakeSolver(recaptcha_v2_result="TOKEN_BACKUP")
        router, guard = _build_router(
            [("capsolver", primary), ("gpt4v", gpt), ("twocaptcha", backup)],
        )

        token = await router.solve_recaptcha_v2(
            site_key="x",
            page_url="https://example.com",
        )

        assert token == "TOKEN_BACKUP"
        assert len(gpt.calls) == 1
        # gpt4v tiene coste 0 para reCAPTCHA y refunde si lanza NotImplementedError
        assert guard.total_spent_cents == pytest.approx(0.088)

    async def test_budget_blocks_provider_when_cost_exceeds_remaining(self) -> None:
        primary = _FakeSolver(recaptcha_v2_result="TOKEN_PRIMARY")
        router, guard = _build_router([("capsolver", primary)], cap_cents=0.05)

        with pytest.raises(CaptchaSolverError, match="budget"):
            await router.solve_recaptcha_v2(
                site_key="x",
                page_url="https://example.com",
            )
        assert primary.calls == []
        assert guard.total_spent_cents == 0.0

    async def test_budget_falls_through_to_cheaper_provider_when_skipped(self) -> None:
        # capsolver bloqueado por budget; gpt4v (gratis para reCAPTCHA) skip
        # via NotImplementedError; finalmente llega a twocaptcha si caben sus
        # 0.088 cents en el cap. Cap = 0.088 alcanza para twocaptcha pero no
        # acumulado con capsolver (0.08 + 0.088 = 0.168 > cap).
        primary = _FakeSolver(recaptcha_v2_result="TOKEN_PRIMARY")
        gpt = _FakeSolver(recaptcha_v2_result=NotImplementedError("no soportado"))
        backup = _FakeSolver(recaptcha_v2_result="TOKEN_BACKUP")
        router, guard = _build_router(
            [("capsolver", primary), ("gpt4v", gpt), ("twocaptcha", backup)],
            cap_cents=0.088,
        )

        # Primer solve consume 0.08 con capsolver
        token1 = await router.solve_recaptcha_v2(
            site_key="x",
            page_url="https://example.com",
        )
        assert token1 == "TOKEN_PRIMARY"
        assert guard.total_spent_cents == pytest.approx(0.08)

        # Segundo solve: capsolver no cabe (0.08 + 0.08 = 0.16 > 0.088),
        # gpt4v skip, twocaptcha tampoco cabe (0.08 + 0.088 = 0.168 > 0.088).
        # Esperamos error de budget.
        with pytest.raises(CaptchaSolverError, match="budget"):
            await router.solve_recaptcha_v2(
                site_key="x",
                page_url="https://example.com",
            )

    async def test_image_text_uses_gpt_fallback(self) -> None:
        primary = _FakeSolver(image_result=CaptchaSolverError("capsolver image fail"))
        backup = _FakeSolver(image_result=CaptchaSolverError("twocaptcha image fail"))
        gpt = _FakeSolver(image_result="ABCDE")
        router, guard = _build_router(
            [("capsolver", primary), ("twocaptcha", backup), ("gpt4v", gpt)],
        )

        text = await router.solve_image_text(image_b64="aGk=", hint="texto")

        assert text == "ABCDE"
        # Solo GPT-4V dejo cargo aplicado (refund de los anteriores)
        assert guard.total_spent_cents == pytest.approx(0.50)

    async def test_total_spent_cents_property_delegates_to_guard(self) -> None:
        primary = _FakeSolver(turnstile_result="TS_OK")
        router, guard = _build_router([("capsolver", primary)])

        assert router.total_spent_cents == 0.0
        await router.solve_cloudflare_turnstile(
            site_key="0x4",
            page_url="https://example.com",
        )
        assert router.total_spent_cents == guard.total_spent_cents
        assert router.total_spent_cents == pytest.approx(0.08)

    async def test_empty_response_treated_as_failure(self) -> None:
        primary = _FakeSolver(recaptcha_v2_result="")
        backup = _FakeSolver(recaptcha_v2_result="OK")
        router, guard = _build_router(
            [("capsolver", primary), ("twocaptcha", backup)],
        )

        token = await router.solve_recaptcha_v2(
            site_key="x",
            page_url="https://example.com",
        )
        assert token == "OK"
        assert guard.total_spent_cents == pytest.approx(0.088)

    async def test_unknown_exception_does_not_crash_router(self) -> None:
        primary = _FakeSolver(recaptcha_v2_result=RuntimeError("boom"))
        backup = _FakeSolver(recaptcha_v2_result="OK")
        router, _ = _build_router(
            [("capsolver", primary), ("twocaptcha", backup)],
        )

        token = await router.solve_recaptcha_v2(
            site_key="x",
            page_url="https://example.com",
        )
        assert token == "OK"

    async def test_requires_at_least_one_provider(self) -> None:
        guard = BudgetGuard(daily_cap_cents=10.0)
        with pytest.raises(ValueError, match="al menos un provider"):
            CaptchaSolverRouter(providers=[], budget_guard=guard)

    async def test_provider_costs_override(self) -> None:
        primary = _FakeSolver(hcaptcha_result="HC_OK")
        guard = BudgetGuard(daily_cap_cents=100.0)
        router = CaptchaSolverRouter(
            providers=[("capsolver", primary)],
            budget_guard=guard,
            provider_costs={"capsolver": CaptchaCostTable(hcaptcha=0.25)},
        )
        await router.solve_hcaptcha(site_key="x", page_url="https://example.com")
        assert guard.total_spent_cents == pytest.approx(0.25)


class TestBudgetGuard:
    def test_try_charge_within_cap(self) -> None:
        guard = BudgetGuard(daily_cap_cents=10.0)
        assert guard.try_charge(3.0) is True
        assert guard.total_spent_cents == 3.0
        assert guard.remaining_cents() == 7.0

    def test_try_charge_rejects_when_exceeds(self) -> None:
        guard = BudgetGuard(daily_cap_cents=5.0)
        assert guard.try_charge(4.0) is True
        assert guard.try_charge(2.0) is False
        assert guard.total_spent_cents == 4.0

    def test_can_afford_does_not_mutate(self) -> None:
        guard = BudgetGuard(daily_cap_cents=10.0)
        assert guard.can_afford(5.0) is True
        assert guard.total_spent_cents == 0.0

    def test_refund_lowers_spent_but_not_below_zero(self) -> None:
        guard = BudgetGuard(daily_cap_cents=10.0)
        guard.try_charge(2.0)
        guard.refund(5.0)
        assert guard.total_spent_cents == 0.0

    def test_negative_cap_rejected(self) -> None:
        with pytest.raises(ValueError):
            BudgetGuard(daily_cap_cents=-1.0)

    def test_negative_charge_rejected(self) -> None:
        guard = BudgetGuard(daily_cap_cents=10.0)
        with pytest.raises(ValueError):
            guard.try_charge(-1.0)

    def test_reset_clears_counter(self) -> None:
        guard = BudgetGuard(daily_cap_cents=10.0)
        guard.try_charge(5.0)
        guard.reset()
        assert guard.total_spent_cents == 0.0
