"""BudgetGuard: cap diario de gasto thread-safe para resolver CAPTCHAs.

Politica:
- Acumula `total_spent_cents` por dia UTC. Cuando llega un nuevo dia UTC,
  el contador se resetea automaticamente.
- `try_charge(cents)` es atomica: si el cargo nuevo supera el cap diario,
  retorna False y NO suma; en caso contrario suma y retorna True.
- Usa threading.Lock porque el adapter puede ser invocado tanto desde un
  pool de threads (Temporal activities con `to_thread`) como desde el loop
  asyncio principal. La operacion es O(1) y no bloquea significativamente
  el event loop.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime


class BudgetGuard:
    """Limita el gasto acumulado en cents por dia UTC."""

    def __init__(self, *, daily_cap_cents: float) -> None:
        if daily_cap_cents < 0:
            raise ValueError("daily_cap_cents no puede ser negativo")
        self._daily_cap_cents = daily_cap_cents
        self._spent_today: float = 0.0
        self._current_day: date = datetime.now(UTC).date()
        self._lock = threading.Lock()

    @property
    def daily_cap_cents(self) -> float:
        return self._daily_cap_cents

    @property
    def total_spent_cents(self) -> float:
        """Cents gastados en el dia UTC actual (con rollover automatico)."""
        with self._lock:
            self._rollover_if_new_day_locked()
            return self._spent_today

    def remaining_cents(self) -> float:
        """Cuanto queda hasta llegar al cap (clamp >= 0)."""
        with self._lock:
            self._rollover_if_new_day_locked()
            remaining = self._daily_cap_cents - self._spent_today
            return max(remaining, 0.0)

    def can_afford(self, cents: float) -> bool:
        """Indica si el siguiente cargo cabria sin rebasar el cap.

        Util para chequeos previos sin reservar gasto.
        """
        if cents < 0:
            raise ValueError("cents no puede ser negativo")
        with self._lock:
            self._rollover_if_new_day_locked()
            return self._spent_today + cents <= self._daily_cap_cents

    def try_charge(self, cents: float) -> bool:
        """Intenta sumar `cents` al contador del dia. Atomico.

        Retorna True si el cargo se aplico, False si rebasaria el cap (sin
        modificar el contador).
        """
        if cents < 0:
            raise ValueError("cents no puede ser negativo")
        with self._lock:
            self._rollover_if_new_day_locked()
            if self._spent_today + cents > self._daily_cap_cents:
                return False
            self._spent_today += cents
            return True

    def refund(self, cents: float) -> None:
        """Devuelve cents al budget (ej. cuando un solve fallo y el provider
        no cobro). Nunca baja de cero."""
        if cents < 0:
            raise ValueError("cents no puede ser negativo")
        with self._lock:
            self._rollover_if_new_day_locked()
            self._spent_today = max(self._spent_today - cents, 0.0)

    def reset(self) -> None:
        """Resetea el contador del dia (uso administrativo / tests)."""
        with self._lock:
            self._spent_today = 0.0
            self._current_day = datetime.now(UTC).date()

    def _rollover_if_new_day_locked(self) -> None:
        today = datetime.now(UTC).date()
        if today != self._current_day:
            self._current_day = today
            self._spent_today = 0.0
