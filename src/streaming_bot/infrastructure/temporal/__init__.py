"""Adaptadores Temporal.io para orquestacion durable.

Reemplaza el InMemoryJobQueue (que pierde estado en restart) por flujos
que sobreviven crashes, restarts y deploys. Especialmente critico para:
- Warming pipelines de cuentas (14-21 dias de duracion).
- Distribucion de catalogo a multi-distribuidor (puede tomar horas).
- Re-tries con backoff exponencial sin pelear con la cola.

Componentes:
- `TemporalClientFactory`: builder del Client con TLS opcional.
- `TemporalJobQueue`: implementa IJobQueue (signal a un workflow).
- `WarmingWorkflow`: pipeline persistente de calentamiento de cuenta.
- `DailyRunWorkflow`: ejecuta un plan diario (calls al StreamOrchestrator).
- `activities/*`: thin wrappers async que invocan use cases del domain.
"""

from streaming_bot.infrastructure.temporal.client_factory import (
    TemporalClientConfig,
    TemporalClientFactory,
)
from streaming_bot.infrastructure.temporal.job_queue import TemporalJobQueue
from streaming_bot.infrastructure.temporal.workflows.daily_run import DailyRunWorkflow
from streaming_bot.infrastructure.temporal.workflows.warming import (
    WarmingPolicyDTO,
    WarmingWorkflow,
)

__all__ = [
    "DailyRunWorkflow",
    "TemporalClientConfig",
    "TemporalClientFactory",
    "TemporalJobQueue",
    "WarmingPolicyDTO",
    "WarmingWorkflow",
]
