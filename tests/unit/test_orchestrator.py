"""Tests del StreamOrchestrator.

Cubre el bug critico arreglado en Mes 1: la politica de retry exponencial
(Tenacity AsyncRetrying) ahora si dispara cuando el use case re-lanza
TransientError. Antes el use case capturaba y devolvia failed, y el retry
nunca corria.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import structlog

from streaming_bot.application.orchestrator import (
    OrchestratorConfig,
    StreamOrchestrator,
)
from streaming_bot.application.stream_song import StreamSongRequest, StreamSongUseCase
from streaming_bot.domain.exceptions import TargetSiteError
from streaming_bot.domain.value_objects import StreamResult


@pytest.fixture
def cheap_config() -> OrchestratorConfig:
    """Backoff minimo para que los tests no tarden segundos."""
    return OrchestratorConfig(concurrency=2, max_retries=3, retry_backoff_seconds=0.001)


def _make_orchestrator(
    use_case: StreamSongUseCase,
    config: OrchestratorConfig,
) -> StreamOrchestrator:
    return StreamOrchestrator(
        use_case=use_case,
        config=config,
        logger=structlog.get_logger("test_orchestrator"),
    )


class TestStreamOrchestratorRetry:
    async def test_retries_until_success_on_transient_error(
        self,
        cheap_config: OrchestratorConfig,
    ) -> None:
        """Si execute lanza TransientError las primeras veces y luego retorna
        ok, el orchestrator debe devolver el ok final tras los retries."""
        use_case = AsyncMock(spec=StreamSongUseCase)
        ok_result = StreamResult.ok(account_id="a1", duration_ms=100)
        use_case.execute.side_effect = [
            TargetSiteError("blip 1"),
            TargetSiteError("blip 2"),
            ok_result,
        ]

        orchestrator = _make_orchestrator(use_case, cheap_config)
        summary = await orchestrator.run([StreamSongRequest(account_id="a1", target_url="https://x")])

        assert summary.total == 1
        assert summary.succeeded == 1
        assert summary.failed == 0
        assert use_case.execute.await_count == 3

    async def test_retries_exhausted_returns_failed_result_not_raises(
        self,
        cheap_config: OrchestratorConfig,
    ) -> None:
        """Si TODOS los intentos lanzan TransientError, el orchestrator NO
        debe propagar la excepcion (rompiendo asyncio.as_completed): debe
        capturarla en _run_one y devolver StreamResult.failed."""
        use_case = AsyncMock(spec=StreamSongUseCase)
        use_case.execute.side_effect = TargetSiteError("permanente blip")

        orchestrator = _make_orchestrator(use_case, cheap_config)
        summary = await orchestrator.run(
            [StreamSongRequest(account_id="a2", target_url="https://x")],
        )

        assert summary.total == 1
        assert summary.succeeded == 0
        assert summary.failed == 1
        result = summary.results[0]
        assert not result.success
        assert result.error_message and "transient_retries_exhausted" in result.error_message
        assert use_case.execute.await_count == cheap_config.max_retries

    async def test_no_retry_on_non_transient_error(
        self,
        cheap_config: OrchestratorConfig,
    ) -> None:
        """Errores que NO son TransientError (e.g. ValueError) no deberian
        ser reintentados; deben propagarse fuera del orchestrator."""
        use_case = AsyncMock(spec=StreamSongUseCase)
        use_case.execute.side_effect = ValueError("bug en use case")

        orchestrator = _make_orchestrator(use_case, cheap_config)

        with pytest.raises(ValueError, match="bug en use case"):
            await orchestrator.run(
                [StreamSongRequest(account_id="a3", target_url="https://x")],
            )

        assert use_case.execute.await_count == 1
