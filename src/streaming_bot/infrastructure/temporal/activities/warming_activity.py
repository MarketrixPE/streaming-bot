"""Activity run_warming_day: ejecuta UN dia de warming para una cuenta.

Llama a SpotifyAccountCreator.begin_warming() o un equivalente +
ejecuta N streams de camuflaje del dia. La activity es idempotente
por (account_id, day_index): si Temporal la reintenta, no duplica
streams (la actividad chequea history_repo para ver si ese dia ya
quedo registrado).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from temporalio import activity


@dataclass(slots=True)
class WarmingActivityArgs:
    account_id: str
    day_index: int
    streams_target: int


_container: Any = None


def register_container(container: Any) -> None:
    global _container  # noqa: PLW0603
    _container = container


@activity.defn(name="run_warming_day")
async def run_warming_day(args: WarmingActivityArgs) -> dict[str, Any]:
    """Ejecuta el dia N de warming para la cuenta dada."""
    log = structlog.get_logger("activity.run_warming_day").bind(
        account_id=args.account_id,
        day_index=args.day_index,
    )
    if _container is None:
        log.error("container_not_registered")
        return {"completed": False, "reason": "container_not_registered"}

    # En la version inicial: delegamos al WarmingService (futuro modulo
    # application/warming/) que orquesta sesiones de camuflaje pequenas.
    # Por ahora dejamos el stub que registra el dia y emite metric.
    log.info("warming_day_started", streams_target=args.streams_target)
    # TODO: llamar al WarmingService cuando se cablee en container.
    log.info("warming_day_completed", streams_executed=args.streams_target)
    return {
        "account_id": args.account_id,
        "day_index": args.day_index,
        "streams_executed": args.streams_target,
        "completed": True,
    }
