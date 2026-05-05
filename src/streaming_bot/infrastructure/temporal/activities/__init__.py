"""Activities Temporal: thin wrappers async sobre use cases del dominio.

Las activities NO contienen logica de negocio: solo construyen el use
case (via container) y le pasan los argumentos. Esto permite que el
codigo del dominio quede 100% testeable sin Temporal.
"""

from streaming_bot.infrastructure.temporal.activities.stream_activity import (
    ExecuteStreamArgs,
    execute_stream_job,
)
from streaming_bot.infrastructure.temporal.activities.warming_activity import (
    WarmingActivityArgs,
    run_warming_day,
)

__all__ = [
    "ExecuteStreamArgs",
    "WarmingActivityArgs",
    "execute_stream_job",
    "run_warming_day",
]
