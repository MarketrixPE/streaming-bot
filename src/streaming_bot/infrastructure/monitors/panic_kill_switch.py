"""Implementacion del ``IPanicKillSwitch`` basada en filesystem.

Diseno:
- ``trigger`` crea un archivo marker con metadata JSON (reason, timestamp,
  alerta) que cualquier worker puede ``os.path.exists()`` para abortar.
- ``is_active`` chequea el marker.
- ``reset`` elimina el marker. Solo permitido con ``authorized_by`` y
  ``justification`` no vacios; cualquier reset queda en un audit log
  append-only.
- ``subscribe_callback`` permite registrar handlers in-process (ej. el
  scheduler) que reciban la alerta cuando ``trigger`` se dispara.

El uso del filesystem hace el switch resistente a crashes de procesos:
si el orchestrator cae con el switch activo, el siguiente arranque vera
el marker y rehusara levantar workers.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from structlog.stdlib import BoundLogger

from streaming_bot.domain.ports.distributor_monitor import (
    DistributorAlert,
    IPanicKillSwitch,
)

KillSwitchCallback = Callable[[DistributorAlert | None, str], Awaitable[None] | None]
"""Callback ejecutado cuando el switch se dispara.

Recibe la alerta disparadora (puede ser ``None``) y la razon textual.
Soporta funciones sincronas y asincronas.
"""


class FilesystemPanicKillSwitch(IPanicKillSwitch):
    """Kill-switch persistente en filesystem.

    Args:
        marker_path: archivo a crear cuando el switch se dispara.
            Por defecto ``./.kill_switch_active``.
        audit_log_path: archivo append-only con eventos de trigger/reset.
        logger: logger structlog.
    """

    def __init__(
        self,
        *,
        marker_path: Path = Path("./.kill_switch_active"),
        audit_log_path: Path = Path("./kill_switch_audit.log"),
        logger: BoundLogger,
    ) -> None:
        self._marker_path = marker_path
        self._audit_log_path = audit_log_path
        self._logger = logger.bind(component="panic_kill_switch")
        self._callbacks: list[KillSwitchCallback] = []

    # ── Suscripcion de callbacks ─────────────────────────────────────────────
    def subscribe_callback(self, callback: KillSwitchCallback) -> None:
        """Registra un callback que se ejecuta tras ``trigger``.

        El scheduler de ramp-up debe suscribir un handler que pare workers.
        """
        self._callbacks.append(callback)

    # ── Contrato ``IPanicKillSwitch`` ────────────────────────────────────────
    async def is_active(self) -> bool:
        return self._marker_path.exists()

    async def trigger(
        self,
        *,
        reason: str,
        triggering_alert: DistributorAlert | None = None,
    ) -> None:
        """Activa el kill-switch y notifica a callbacks suscritos.

        Es idempotente: si el switch ya esta activo, solo agrega un evento
        al audit log y NO vuelve a invocar callbacks (evita doble apagado).
        """
        already_active = self._marker_path.exists()
        payload: dict[str, Any] = {
            "reason": reason,
            "triggered_at": datetime.now(UTC).isoformat(),
            "alert": _alert_to_dict(triggering_alert),
        }
        try:
            self._marker_path.parent.mkdir(parents=True, exist_ok=True)
            self._marker_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            # Falla escribiendo el marker es CRITICA; lanzamos asi el caller
            # se entera y no asume "todo bien".
            self._logger.error("kill_switch_marker_write_failed", error=str(exc))
            raise

        self._append_audit("trigger", payload)
        self._logger.critical(
            "kill_switch_triggered",
            reason=reason,
            already_active=already_active,
            alert_category=(triggering_alert.category.value if triggering_alert else None),
        )
        if already_active:
            return
        await self._invoke_callbacks(triggering_alert, reason)

    async def reset(self, *, authorized_by: str, justification: str) -> None:
        """Desactiva el switch. Solo permitido con autorizador y justificacion."""
        if not authorized_by or not authorized_by.strip():
            raise ValueError("authorized_by es obligatorio para resetear el kill-switch")
        if not justification or not justification.strip():
            raise ValueError("justification es obligatoria para resetear el kill-switch")

        existed = self._marker_path.exists()
        if existed:
            try:
                self._marker_path.unlink()
            except OSError as exc:
                self._logger.error("kill_switch_marker_delete_failed", error=str(exc))
                raise

        self._append_audit(
            "reset",
            {
                "authorized_by": authorized_by.strip(),
                "justification": justification.strip(),
                "reset_at": datetime.now(UTC).isoformat(),
                "marker_existed": existed,
            },
        )
        self._logger.warning(
            "kill_switch_reset",
            authorized_by=authorized_by,
            marker_existed=existed,
        )

    # ── Helpers privados ─────────────────────────────────────────────────────
    async def _invoke_callbacks(self, alert: DistributorAlert | None, reason: str) -> None:
        """Invoca callbacks aislando excepciones (un mal callback no rompe)."""
        for callback in self._callbacks:
            try:
                result = callback(alert, reason)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                self._logger.warning(
                    "kill_switch_callback_failed",
                    callback=getattr(callback, "__name__", repr(callback)),
                    error=str(exc),
                )

    def _append_audit(self, event: str, payload: dict[str, Any]) -> None:
        """Append-only JSON line en el audit log."""
        record = {"event": event, **payload}
        try:
            self._audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._audit_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            self._logger.warning("kill_switch_audit_write_failed", error=str(exc))


def _alert_to_dict(alert: DistributorAlert | None) -> dict[str, Any] | None:
    """Serializa una ``DistributorAlert`` a dict JSON-friendly."""
    if alert is None:
        return None
    raw = asdict(alert)
    # Convertimos enums + datetime a str para que ``json.dumps`` no falle.
    raw["platform"] = alert.platform.value
    raw["severity"] = alert.severity.value
    raw["category"] = alert.category.value
    raw["detected_at"] = alert.detected_at.isoformat()
    raw["affected_song_titles"] = list(alert.affected_song_titles)
    return raw


# Helper opcional: utilidad sincrona para que workers Python no-async puedan
# hacer un fast-check antes de dormir. No forma parte del Protocol pero es
# practica.
def is_kill_switch_marker_present(marker_path: Path = Path("./.kill_switch_active")) -> bool:
    """Chequeo sincrono del marker. Util desde codigo no-async."""
    return marker_path.exists()


# Re-export para tipado en otros modulos sin acoplar al asyncio si no es necesario.
__all__ = [
    "FilesystemPanicKillSwitch",
    "KillSwitchCallback",
    "is_kill_switch_marker_present",
]
