"""WarmingWorkflow: pipeline durable de calentamiento de cuenta nueva.

Una cuenta recien creada debe ejecutar comportamiento humano de bajo
volumen durante N dias (14 por defecto) antes de ser usada para streams
target. Antes esto vivia en memoria y se perdia en cada restart. Ahora
el workflow Temporal:

- Persiste el dia actual de warming.
- Programa actividades por dia con sleep durable (`workflow.sleep`).
- Recibe signals para abortar (cuenta baneada o flagged).
- Expone query `progress` para que el dashboard vea el avance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from streaming_bot.infrastructure.temporal.activities.warming_activity import (
        WarmingActivityArgs,
        run_warming_day,
    )


@dataclass(slots=True)
class WarmingPolicyDTO:
    """Mirror serializable de domain.WarmingPolicy."""

    account_id: str
    days_warming: int = 14
    streams_per_day: int = 6
    must_complete_artist_follows: int = 8
    must_complete_playlist_follows: int = 5
    must_complete_track_likes: int = 12


@workflow.defn(name="WarmingWorkflow", sandboxed=False)
class WarmingWorkflow:
    """Calentamiento durable de N dias para una cuenta."""

    def __init__(self) -> None:
        self._current_day: int = 0
        self._completed: bool = False
        self._aborted_reason: str | None = None
        self._policy: WarmingPolicyDTO | None = None

    @workflow.run
    async def run(self, policy: WarmingPolicyDTO) -> dict[str, object]:
        self._policy = policy
        for day in range(1, policy.days_warming + 1):
            if self._aborted_reason is not None:
                break
            self._current_day = day
            await workflow.execute_activity(
                run_warming_day,
                WarmingActivityArgs(
                    account_id=policy.account_id,
                    day_index=day,
                    streams_target=policy.streams_per_day,
                ),
                start_to_close_timeout=timedelta(hours=2),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(minutes=10),
                    maximum_attempts=4,
                ),
            )
            # Sleep durable de 24h hasta el siguiente "dia" de warming.
            # Si el worker reinicia, Temporal mantiene el timer.
            await workflow.sleep(timedelta(hours=24))

        self._completed = self._aborted_reason is None
        return {
            "account_id": policy.account_id,
            "completed_days": self._current_day,
            "total_days": policy.days_warming,
            "completed": self._completed,
            "aborted_reason": self._aborted_reason,
        }

    @workflow.signal(name="abort")
    def abort(self, reason: str) -> None:
        """Aborta el warming (cuenta baneada / flagged manualmente)."""
        self._aborted_reason = reason

    @workflow.query(name="progress")
    def progress(self) -> dict[str, object]:
        if self._policy is None:
            return {"current_day": 0, "total_days": 0, "completed": False}
        return {
            "account_id": self._policy.account_id,
            "current_day": self._current_day,
            "total_days": self._policy.days_warming,
            "completed": self._completed,
            "aborted_reason": self._aborted_reason,
        }
