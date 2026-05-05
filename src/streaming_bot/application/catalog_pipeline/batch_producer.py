"""``BatchProducer``: orquesta N briefs -> N pistas en paralelo.

Politicas:

- Concurrencia limitada con ``asyncio.Semaphore`` (evita reventar el rate
  limit del proveedor IA).
- Budget guard: estima un coste fijo por pista; cuando el acumulado supera
  ``budget_cents_cap`` deja de despachar nuevos briefs (los pendientes se
  reportan como ``skipped_over_budget``).
- Aislamiento de fallos: una excepcion en un brief no aborta los demas; se
  acumula en ``BatchResult.failures`` para auditoria.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from streaming_bot.domain.catalog_pipeline.track_brief import TrackBrief

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

    from streaming_bot.application.catalog_pipeline.produce_track_use_case import (
        ProducedTrack,
        ProduceTrackUseCase,
    )


@dataclass(slots=True)
class BatchResult:
    """Resultado agregado de un batch.

    Atributos:
        produced: tracks generados con exito.
        failures: lista de tuplas (brief, mensaje de error).
        skipped_over_budget: briefs no procesados por exceder el cap.
        spent_cents: estimacion total de coste consumido.
    """

    produced: list[ProducedTrack] = field(default_factory=list)
    failures: list[tuple[TrackBrief, str]] = field(default_factory=list)
    skipped_over_budget: list[TrackBrief] = field(default_factory=list)
    spent_cents: float = 0.0


class BatchProducer:
    """Ejecutor concurrente de N briefs sobre un ``ProduceTrackUseCase``.

    El use case se inyecta (DIP) y el producer se concentra en concurrencia
    + presupuesto. Es seguro reusar la misma instancia entre batches; el
    estado del budget se reinicia por llamada a ``produce_batch``.
    """

    def __init__(
        self,
        *,
        use_case: ProduceTrackUseCase,
        max_concurrency: int,
        cost_per_track_cents: float,
        budget_cents_cap: float,
        logger: BoundLogger,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError(f"max_concurrency debe ser >0, recibido {max_concurrency}")
        if cost_per_track_cents < 0:
            raise ValueError(
                f"cost_per_track_cents no puede ser negativo: {cost_per_track_cents}",
            )
        if budget_cents_cap < 0:
            raise ValueError(
                f"budget_cents_cap no puede ser negativo: {budget_cents_cap}",
            )
        self._use_case = use_case
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._cost_per_track = cost_per_track_cents
        self._budget_cap = budget_cents_cap
        self._log = logger.bind(component="batch_producer")

    async def produce_batch(self, briefs: list[TrackBrief]) -> BatchResult:
        """Procesa ``briefs`` y devuelve un ``BatchResult`` agregado."""
        result = BatchResult()
        budget_lock = asyncio.Lock()
        budget_state = _BudgetState(spent=0.0)

        self._log.info(
            "batch.start",
            briefs_count=len(briefs),
            budget_cap_cents=self._budget_cap,
            cost_per_track=self._cost_per_track,
        )

        tasks = [
            asyncio.create_task(
                self._run_one(
                    brief,
                    result=result,
                    budget_lock=budget_lock,
                    budget_state=budget_state,
                ),
            )
            for brief in briefs
        ]
        if tasks:
            await asyncio.gather(*tasks)

        result.spent_cents = budget_state.spent
        self._log.info(
            "batch.done",
            produced=len(result.produced),
            failures=len(result.failures),
            skipped=len(result.skipped_over_budget),
            spent_cents=result.spent_cents,
        )
        return result

    async def _run_one(
        self,
        brief: TrackBrief,
        *,
        result: BatchResult,
        budget_lock: asyncio.Lock,
        budget_state: _BudgetState,
    ) -> None:
        """Ejecuta un brief respetando semaforo y budget."""
        async with budget_lock:
            projected = budget_state.spent + self._cost_per_track
            if projected > self._budget_cap:
                result.skipped_over_budget.append(brief)
                self._log.warning(
                    "batch.skipped_over_budget",
                    niche=brief.niche,
                    spent=budget_state.spent,
                    cap=self._budget_cap,
                )
                return
            budget_state.spent = projected

        async with self._semaphore:
            try:
                produced = await self._use_case.execute(brief)
            except Exception as exc:
                async with budget_lock:
                    budget_state.spent -= self._cost_per_track
                result.failures.append((brief, str(exc)))
                self._log.warning(
                    "batch.failure",
                    niche=brief.niche,
                    mood=brief.mood,
                    error=str(exc),
                )
                return
            result.produced.append(produced)


@dataclass(slots=True)
class _BudgetState:
    """Mutable budget counter compartido entre tareas concurrentes."""

    spent: float
