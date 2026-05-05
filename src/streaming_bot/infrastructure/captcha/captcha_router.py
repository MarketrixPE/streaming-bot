"""CaptchaSolverRouter: failover ordenado entre N ICaptchaSolver con
budget guard.

Politica:
1. Recorre los providers en el orden recibido.
2. Por cada provider:
   - Consulta `BudgetGuard.try_charge(cost)` con el coste estimado del
     metodo. Si no cabe en el budget diario, salta al siguiente.
   - Llama al metodo `solve_*`. Si tiene exito, retorna; deja el cargo
     aplicado.
   - Si falla con `CaptchaSolverError`, refunde el cargo y prueba el
     siguiente provider.
   - Si lanza `NotImplementedError` (ej. GPT-4V para reCAPTCHA), refunde
     y salta sin contarlo como error.
3. Si NINGUN provider responde, lanza `CaptchaSolverError` con la cadena
   de errores.

Costes por defecto (CapSolver Q4 2025; sobrecarga +10% para 2Captcha;
GPT-4V plana en imagen). El caller puede sobreescribir cualquier coste.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import structlog

from streaming_bot.domain.ports.captcha_solver import (
    CaptchaSolverError,
    ICaptchaSolver,
)
from streaming_bot.infrastructure.captcha.budget_guard import BudgetGuard


@dataclass(frozen=True, slots=True)
class CaptchaCostTable:
    """Coste estimado por solve, en cents (USD * 100), por tipo de captcha."""

    recaptcha_v2: float = 0.08
    recaptcha_v3: float = 0.12
    hcaptcha: float = 0.10
    turnstile: float = 0.08
    image_text: float = 0.03


# Tarifas por defecto por provider (claves logicas). Cada provider concreto
# puede registrarse con su propia tabla via `provider_costs`.
DEFAULT_PROVIDER_COSTS: Mapping[str, CaptchaCostTable] = {
    "capsolver": CaptchaCostTable(),
    "twocaptcha": CaptchaCostTable(
        recaptcha_v2=0.088,
        recaptcha_v3=0.132,
        hcaptcha=0.110,
        turnstile=0.088,
        image_text=0.050,
    ),
    "gpt4v": CaptchaCostTable(
        recaptcha_v2=0.0,
        recaptcha_v3=0.0,
        hcaptcha=0.0,
        turnstile=0.0,
        image_text=0.50,
    ),
}


@dataclass(slots=True)
class _ProviderEntry:
    name: str
    solver: ICaptchaSolver
    costs: CaptchaCostTable = field(default_factory=CaptchaCostTable)


class CaptchaSolverRouter(ICaptchaSolver):
    """Router con failover ordenado y budget cap acumulado en cents."""

    def __init__(
        self,
        *,
        providers: Sequence[tuple[str, ICaptchaSolver]],
        budget_guard: BudgetGuard,
        provider_costs: Mapping[str, CaptchaCostTable] | None = None,
    ) -> None:
        if not providers:
            raise ValueError("CaptchaSolverRouter requiere al menos un provider")
        cost_table = dict(DEFAULT_PROVIDER_COSTS)
        if provider_costs:
            cost_table.update(provider_costs)
        self._entries: list[_ProviderEntry] = [
            _ProviderEntry(
                name=name,
                solver=solver,
                costs=cost_table.get(name, CaptchaCostTable()),
            )
            for name, solver in providers
        ]
        self._budget = budget_guard
        self._log = structlog.get_logger("captcha_router")

    @property
    def total_spent_cents(self) -> float:
        """Cents gastados acumulados (delegado al BudgetGuard)."""
        return self._budget.total_spent_cents

    @property
    def budget_guard(self) -> BudgetGuard:
        return self._budget

    async def solve_recaptcha_v2(self, *, site_key: str, page_url: str) -> str:
        return await self._dispatch(
            method_name="solve_recaptcha_v2",
            cost_attr="recaptcha_v2",
            kwargs={"site_key": site_key, "page_url": page_url},
        )

    async def solve_recaptcha_v3(
        self,
        *,
        site_key: str,
        page_url: str,
        action: str,
        min_score: float,
    ) -> str:
        return await self._dispatch(
            method_name="solve_recaptcha_v3",
            cost_attr="recaptcha_v3",
            kwargs={
                "site_key": site_key,
                "page_url": page_url,
                "action": action,
                "min_score": min_score,
            },
        )

    async def solve_hcaptcha(self, *, site_key: str, page_url: str) -> str:
        return await self._dispatch(
            method_name="solve_hcaptcha",
            cost_attr="hcaptcha",
            kwargs={"site_key": site_key, "page_url": page_url},
        )

    async def solve_cloudflare_turnstile(self, *, site_key: str, page_url: str) -> str:
        return await self._dispatch(
            method_name="solve_cloudflare_turnstile",
            cost_attr="turnstile",
            kwargs={"site_key": site_key, "page_url": page_url},
        )

    async def solve_image_text(self, *, image_b64: str, hint: str) -> str:
        return await self._dispatch(
            method_name="solve_image_text",
            cost_attr="image_text",
            kwargs={"image_b64": image_b64, "hint": hint},
        )

    async def _dispatch(
        self,
        *,
        method_name: str,
        cost_attr: str,
        kwargs: Mapping[str, object],
    ) -> str:
        errors: list[str] = []
        budget_blocked = False

        for entry in self._entries:
            cost = float(getattr(entry.costs, cost_attr))
            charged = self._budget.try_charge(cost) if cost > 0 else True
            if not charged:
                budget_blocked = True
                self._log.warning(
                    "captcha_router.budget_exhausted",
                    provider=entry.name,
                    method=method_name,
                    cost_cents=cost,
                    spent_cents=self._budget.total_spent_cents,
                    cap_cents=self._budget.daily_cap_cents,
                )
                errors.append(f"{entry.name}: budget cap diario alcanzado")
                continue

            method = getattr(entry.solver, method_name)
            try:
                result = await method(**kwargs)
            except NotImplementedError:
                if cost > 0:
                    self._budget.refund(cost)
                self._log.debug(
                    "captcha_router.provider_unsupported",
                    provider=entry.name,
                    method=method_name,
                )
                continue
            except CaptchaSolverError as exc:
                if cost > 0:
                    self._budget.refund(cost)
                errors.append(f"{entry.name}: {exc}")
                self._log.warning(
                    "captcha_router.provider_failed",
                    provider=entry.name,
                    method=method_name,
                    error=str(exc),
                )
                continue
            except Exception as exc:
                if cost > 0:
                    self._budget.refund(cost)
                errors.append(f"{entry.name}: {type(exc).__name__}: {exc}")
                self._log.exception(
                    "captcha_router.provider_unexpected",
                    provider=entry.name,
                    method=method_name,
                )
                continue

            if not isinstance(result, str) or not result:
                if cost > 0:
                    self._budget.refund(cost)
                errors.append(f"{entry.name}: respuesta vacia")
                continue

            self._log.info(
                "captcha_router.solved",
                provider=entry.name,
                method=method_name,
                cost_cents=cost,
                spent_cents=self._budget.total_spent_cents,
            )
            return result

        if budget_blocked and not any(":" in e and "budget cap" not in e for e in errors):
            raise CaptchaSolverError(
                f"captcha router: budget diario agotado ({self._budget.total_spent_cents:.2f}/"
                f"{self._budget.daily_cap_cents:.2f} cents) | errores: {errors}",
            )
        raise CaptchaSolverError(
            f"captcha router: todos los providers fallaron para {method_name} | errores: {errors}",
        )
