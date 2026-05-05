"""Workflows Temporal.io del producto.

Los workflows viven en este modulo para evitar que sean importados a la
ligera desde el resto del codebase (deben importarse SOLO via Temporal
worker registration).
"""

from streaming_bot.infrastructure.temporal.workflows.daily_run import DailyRunWorkflow
from streaming_bot.infrastructure.temporal.workflows.warming import (
    WarmingPolicyDTO,
    WarmingWorkflow,
)

__all__ = ["DailyRunWorkflow", "WarmingPolicyDTO", "WarmingWorkflow"]
