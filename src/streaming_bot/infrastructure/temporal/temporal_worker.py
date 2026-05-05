"""Worker Temporal: registra workflows + activities y los ejecuta.

Despliegue:
- Un proceso por nodo "workers" (Hetzner). Se conecta al Temporal cluster
  del data plane (10.10.0.20:7233) y consume task queues.
- Mantenemos UNA task queue por defecto: "streaming-bot-default".
  En el futuro se separan por DSP (spotify, soundcloud, deezer) y por
  modo (warming, prod).

Ejecucion CLI:
    uv run python -m streaming_bot.infrastructure.temporal.temporal_worker
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog


@dataclass(frozen=True, slots=True)
class TemporalWorkerConfig:
    host: str = "10.10.0.20:7233"
    namespace: str = "default"
    task_queue: str = "streaming-bot-default"
    max_concurrent_activities: int = 50
    max_concurrent_workflow_tasks: int = 100


async def run_worker(
    config: TemporalWorkerConfig,
    *,
    container: object | None = None,
) -> None:
    """Arranca el worker Temporal hasta interrupcion (Ctrl-C / SIGTERM)."""
    log = structlog.get_logger("temporal_worker").bind(
        host=config.host,
        task_queue=config.task_queue,
    )
    try:
        from temporalio.client import Client
        from temporalio.worker import Worker
    except ImportError as exc:
        raise RuntimeError(
            "temporalio no esta instalado. Anade `streaming-bot[temporal]`.",
        ) from exc

    from streaming_bot.infrastructure.temporal.activities import (
        execute_stream_job,
        run_warming_day,
    )
    from streaming_bot.infrastructure.temporal.activities.stream_activity import (
        register_container as register_stream_container,
    )
    from streaming_bot.infrastructure.temporal.activities.warming_activity import (
        register_container as register_warming_container,
    )
    from streaming_bot.infrastructure.temporal.workflows import (
        DailyRunWorkflow,
        WarmingWorkflow,
    )

    if container is not None:
        register_stream_container(container)
        register_warming_container(container)

    client = await Client.connect(config.host, namespace=config.namespace)
    worker = Worker(
        client,
        task_queue=config.task_queue,
        workflows=[DailyRunWorkflow, WarmingWorkflow],
        activities=[execute_stream_job, run_warming_day],
        max_concurrent_activities=config.max_concurrent_activities,
        max_concurrent_workflow_tasks=config.max_concurrent_workflow_tasks,
    )
    log.info("temporal_worker_starting")
    try:
        await worker.run()
    finally:
        log.info("temporal_worker_stopped")


def main() -> None:  # pragma: no cover - CLI entrypoint
    """Entry point CLI."""
    import os

    config = TemporalWorkerConfig(
        host=os.environ.get("SB_TEMPORAL_HOST", "10.10.0.20:7233"),
        namespace=os.environ.get("SB_TEMPORAL_NAMESPACE", "default"),
        task_queue=os.environ.get("SB_TEMPORAL_TASK_QUEUE", "streaming-bot-default"),
    )
    asyncio.run(run_worker(config))


if __name__ == "__main__":  # pragma: no cover
    main()
