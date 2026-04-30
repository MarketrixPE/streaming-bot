"""Orquestador async con concurrencia controlada y retry exponencial."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from streaming_bot.application.stream_song import StreamSongRequest, StreamSongUseCase
from streaming_bot.domain.exceptions import TransientError
from streaming_bot.domain.value_objects import StreamResult

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger


@dataclass(frozen=True, slots=True)
class OrchestratorConfig:
    concurrency: int = 10
    max_retries: int = 3
    retry_backoff_seconds: float = 2.0


@dataclass(frozen=True, slots=True)
class BatchSummary:
    total: int
    succeeded: int
    failed: int
    results: list[StreamResult]


class StreamOrchestrator:
    """Ejecuta múltiples StreamSongRequest en paralelo con backpressure.

    Características:
    - Semaphore: limita el N de browsers vivos a la vez.
    - Tenacity: retry con backoff exponencial sólo para TransientError.
    - Cancelación cooperativa: SIGINT/SIGTERM cancelan tasks limpiamente.
    """

    def __init__(
        self,
        *,
        use_case: StreamSongUseCase,
        config: OrchestratorConfig,
        logger: BoundLogger,
    ) -> None:
        self._use_case = use_case
        self._config = config
        self._log = logger
        self._semaphore = asyncio.Semaphore(config.concurrency)

    async def run(self, requests: Sequence[StreamSongRequest]) -> BatchSummary:
        self._log.info(
            "orchestrator.start",
            total=len(requests),
            concurrency=self._config.concurrency,
        )
        tasks = [asyncio.create_task(self._run_one(req)) for req in requests]
        results: list[StreamResult] = []

        try:
            for finished in asyncio.as_completed(tasks):
                results.append(await finished)
        except asyncio.CancelledError:
            self._log.warning("orchestrator.cancelled")
            for t in tasks:
                t.cancel()
            raise

        succeeded = sum(1 for r in results if r.success)
        summary = BatchSummary(
            total=len(results),
            succeeded=succeeded,
            failed=len(results) - succeeded,
            results=results,
        )
        self._log.info(
            "orchestrator.done",
            total=summary.total,
            succeeded=summary.succeeded,
            failed=summary.failed,
        )
        return summary

    async def _run_one(self, request: StreamSongRequest) -> StreamResult:
        async with self._semaphore:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._config.max_retries),
                wait=wait_exponential(multiplier=self._config.retry_backoff_seconds),
                retry=retry_if_exception_type(TransientError),
                reraise=True,
            ):
                with attempt:
                    return await self._use_case.execute(request)
            raise RuntimeError("retry loop terminó sin resultado")  # pragma: no cover
