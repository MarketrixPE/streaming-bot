"""Orchestrator que corre los monitors en bucle y dispara el kill-switch.

Diseño:
- Constructor recibe lista de ``IDistributorMonitor`` + ``IPanicKillSwitch``
  + ``alert_handler`` (callback para Slack/email/PagerDuty/etc).
- ``run_once()`` ejecuta un ciclo: corre todos los monitors en paralelo,
  agrega alertas, dispara kill-switch si hay severity >= CRITICAL.
- ``run_forever(interval_seconds)`` loopea con jitter y soporte de
  ``asyncio.CancelledError`` para shutdown limpio.
- Defensivo: si un monitor lanza, se loguea WARNING y NO rompe el bucle.
"""

from __future__ import annotations

import asyncio
import inspect
import random
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

from structlog.stdlib import BoundLogger

from streaming_bot.domain.ports.distributor_monitor import (
    AlertSeverity,
    DistributorAlert,
    IDistributorMonitor,
    IPanicKillSwitch,
)

AlertHandler = Callable[[DistributorAlert], Awaitable[None] | None]
"""Handler externo para alertas (Slack, email, PagerDuty...).

Soporta sync y async.
"""


class MonitorOrchestrator:
    """Loop que corre todos los monitors y agrega resultados.

    Args:
        monitors: lista de ``IDistributorMonitor``.
        kill_switch: ``IPanicKillSwitch`` a disparar ante severity critica.
        logger: logger structlog.
        alert_handler: callback opcional para cada alerta detectada.
        check_emails: si True, llama a ``check_emails`` ademas de
            ``login_and_scrape`` en cada ciclo.
        per_monitor_timeout_s: timeout por monitor (defensivo).
    """

    def __init__(
        self,
        *,
        monitors: Sequence[IDistributorMonitor],
        kill_switch: IPanicKillSwitch,
        logger: BoundLogger,
        alert_handler: AlertHandler | None = None,
        check_emails: bool = True,
        per_monitor_timeout_s: float = 120.0,
    ) -> None:
        self._monitors = list(monitors)
        self._kill_switch = kill_switch
        self._logger = logger.bind(component="monitor_orchestrator")
        self._alert_handler = alert_handler
        self._check_emails = check_emails
        self._per_monitor_timeout_s = per_monitor_timeout_s
        self._last_email_check: datetime | None = None

    # ── Bucle ────────────────────────────────────────────────────────────────
    async def run_forever(self, *, interval_seconds: int = 600) -> None:
        """Loop infinito con jitter +-10%. Cancelable via ``asyncio.CancelledError``."""
        if interval_seconds <= 0:
            raise ValueError("interval_seconds debe ser > 0")
        self._logger.info(
            "orchestrator_started",
            monitors=[m.platform.value for m in self._monitors],
            interval=interval_seconds,
        )
        try:
            while True:
                if await self._kill_switch.is_active():
                    self._logger.warning("orchestrator_skip_cycle_kill_switch_active")
                else:
                    await self.run_once()
                jitter = interval_seconds * random.uniform(-0.1, 0.1)  # noqa: S311
                await asyncio.sleep(max(1.0, interval_seconds + jitter))
        except asyncio.CancelledError:
            self._logger.info("orchestrator_cancelled")
            raise

    async def run_once(self) -> list[DistributorAlert]:
        """Ejecuta un ciclo de scraping + email check. Devuelve alertas."""
        scrape_tasks = [self._safe_scrape(monitor) for monitor in self._monitors]
        email_tasks: list[Awaitable[list[DistributorAlert]]] = []
        if self._check_emails:
            email_tasks = [self._safe_check_emails(monitor) for monitor in self._monitors]

        results = await asyncio.gather(*scrape_tasks, *email_tasks, return_exceptions=False)

        alerts: list[DistributorAlert] = []
        for batch in results:
            alerts.extend(batch)

        # Notificar handler de cada alerta.
        if self._alert_handler is not None:
            for alert in alerts:
                await self._invoke_handler(alert)

        # Disparar kill-switch UNA sola vez por la alerta mas critica.
        critical = [a for a in alerts if a.is_kill_switch_trigger]
        if critical:
            most_critical = max(critical, key=_severity_rank)
            already_active = await self._kill_switch.is_active()
            await self._kill_switch.trigger(
                reason=(
                    f"{most_critical.platform.value}/{most_critical.category.value}: "
                    f"{most_critical.message[:240]}"
                ),
                triggering_alert=most_critical,
            )
            self._logger.critical(
                "orchestrator_kill_switch_fired",
                already_active=already_active,
                critical_count=len(critical),
                top_severity=most_critical.severity.value,
            )

        self._last_email_check = datetime.now(UTC)
        self._logger.info(
            "orchestrator_cycle_complete",
            total_alerts=len(alerts),
            critical=len(critical),
        )
        return alerts

    # ── Helpers ──────────────────────────────────────────────────────────────
    async def _safe_scrape(self, monitor: IDistributorMonitor) -> list[DistributorAlert]:
        """Ejecuta ``login_and_scrape`` aislando excepciones por monitor."""
        try:
            return await asyncio.wait_for(
                monitor.login_and_scrape(),
                timeout=self._per_monitor_timeout_s,
            )
        except TimeoutError:
            self._logger.warning(
                "monitor_scrape_timeout",
                platform=monitor.platform.value,
                timeout_s=self._per_monitor_timeout_s,
            )
            return []
        except Exception as exc:
            self._logger.warning(
                "monitor_scrape_failed",
                platform=monitor.platform.value,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return []

    async def _safe_check_emails(self, monitor: IDistributorMonitor) -> list[DistributorAlert]:
        """Ejecuta ``check_emails`` aislando excepciones por monitor."""
        try:
            return await asyncio.wait_for(
                monitor.check_emails(since=self._last_email_check),
                timeout=self._per_monitor_timeout_s,
            )
        except TimeoutError:
            self._logger.warning(
                "monitor_email_timeout",
                platform=monitor.platform.value,
                timeout_s=self._per_monitor_timeout_s,
            )
            return []
        except Exception as exc:
            self._logger.warning(
                "monitor_email_failed",
                platform=monitor.platform.value,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return []

    async def _invoke_handler(self, alert: DistributorAlert) -> None:
        if self._alert_handler is None:
            return
        try:
            result = self._alert_handler(alert)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            self._logger.warning(
                "alert_handler_failed",
                error=str(exc),
                platform=alert.platform.value,
            )


_SEVERITY_ORDER: dict[AlertSeverity, int] = {
    AlertSeverity.INFO: 0,
    AlertSeverity.WARNING: 1,
    AlertSeverity.CRITICAL: 2,
    AlertSeverity.FATAL: 3,
}


def _severity_rank(alert: DistributorAlert) -> int:
    return _SEVERITY_ORDER.get(alert.severity, 0)


__all__ = ["AlertHandler", "MonitorOrchestrator"]
