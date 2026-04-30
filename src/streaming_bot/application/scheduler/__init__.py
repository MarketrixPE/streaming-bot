"""Scheduler temporal del ramp-up.

Componentes:
- ``DailyPlanner``: convierte el catalogo de canciones en un plan diario
  de streams objetivo aplicando ``RampUpPolicy`` por tier y respetando
  el ``safe_ceiling_today`` de cada cancion.
- ``TimeOfDayDistributor``: reparte los streams del plan entre cuentas
  durante las horas activas locales de cada persona.
- ``JitterController``: utilidades puras de jitter para targets, tiempos
  y dias de descanso aleatorio.
- ``InMemoryJobQueue``: cola priorizada por ``scheduled_at`` con
  protocolos para implementaciones persistentes futuras (Redis Streams).
- ``SchedulerWorker``: dispatcher async que consume la cola y ejecuta
  ``PlaylistSessionUseCase`` con concurrencia controlada y respeto al
  panic kill-switch.
- ``SchedulerService``: fachada que cablea todo lo anterior.
"""

from streaming_bot.application.scheduler.daily_planner import (
    DailyPlanner,
    SongDailyTarget,
)
from streaming_bot.application.scheduler.jitter import (
    apply_target_jitter,
    apply_time_jitter,
    should_skip_today,
)
from streaming_bot.application.scheduler.job_queue import (
    IJobQueue,
    IJobQueueStore,
    InMemoryJobQueue,
)
from streaming_bot.application.scheduler.scheduler_service import SchedulerService
from streaming_bot.application.scheduler.time_of_day import (
    ScheduledJob,
    TimeOfDayDistributor,
)
from streaming_bot.application.scheduler.worker import SchedulerWorker, SessionDispatcher

__all__ = [
    "DailyPlanner",
    "IJobQueue",
    "IJobQueueStore",
    "InMemoryJobQueue",
    "ScheduledJob",
    "SchedulerService",
    "SchedulerWorker",
    "SessionDispatcher",
    "SongDailyTarget",
    "TimeOfDayDistributor",
    "apply_target_jitter",
    "apply_time_jitter",
    "should_skip_today",
]
