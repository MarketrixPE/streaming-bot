"""Sesión de browser con primitivas humanas para los 45 behaviors.

Extiende `IBrowserSession` (Sprint 1) con:
- mouse Bezier
- type con delays + typos
- scroll suave con easing
- key press
- viewport runtime
- query helpers (count, visibility, bounding box, text)
- tab blur emulation

Drivers que lo implementan: `CamoufoxDriver` (Sprint 2).
El `PlaywrightDriver` legacy NO implementa este protocolo; sigue cumpliendo
solo `IBrowserSession`. Esto permite migración gradual.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, runtime_checkable

from streaming_bot.domain.ports.browser import IBrowserSession
from streaming_bot.domain.value_objects import Fingerprint, ProxyEndpoint


@runtime_checkable
class IRichBrowserSession(IBrowserSession, Protocol):
    """Sesión de browser con primitivas de comportamiento humano."""

    # ── Navegación extra ────────────────────────────────────────────────────
    async def go_back(self) -> None: ...

    async def reload(self) -> None: ...

    async def current_url(self) -> str: ...

    # ── Mouse humano ────────────────────────────────────────────────────────
    async def human_click(
        self,
        selector: str,
        *,
        button: str = "left",
        click_count: int = 1,
        delay_ms_before: int = 0,
        offset_jitter_px: int = 5,
    ) -> None:
        """Click con curva Bezier al elemento + offset aleatorio + hover previo."""
        ...

    async def human_mouse_move(
        self,
        x: int,
        y: int,
        *,
        duration_ms: int = 500,
        bezier_steps: int = 30,
    ) -> None:
        """Mueve el cursor con curva Bezier hasta (x, y)."""
        ...

    async def hover(self, selector: str, *, duration_ms: int = 200) -> None:
        """Pasa el cursor sobre un elemento sin click."""
        ...

    # ── Teclado humano ──────────────────────────────────────────────────────
    async def human_type(
        self,
        selector: str,
        text: str,
        *,
        wpm: int = 70,
        wpm_stddev: int = 15,
        typo_probability: float = 0.03,
    ) -> None:
        """Escribe en el campo con velocidad humana variable + typos+correcciones."""
        ...

    async def press_key(self, key: str, *, count: int = 1, delay_ms: int = 80) -> None:
        """Presiona una tecla (ej "Space", "ArrowRight", "Tab")."""
        ...

    # ── Scroll humano ───────────────────────────────────────────────────────
    async def human_scroll(
        self,
        *,
        direction: str = "down",  # "up" | "down"
        pixels: int,
        duration_ms: int = 800,
    ) -> None:
        """Scroll con momentum/easing humano (no instantáneo)."""
        ...

    # ── Viewport ────────────────────────────────────────────────────────────
    async def get_viewport_size(self) -> tuple[int, int]:
        """Devuelve (width, height) del viewport actual."""
        ...

    async def set_viewport_size(self, width: int, height: int) -> None:
        """Cambia el tamaño del viewport en runtime (resize ocasional)."""
        ...

    # ── Queries DOM ─────────────────────────────────────────────────────────
    async def query_selector_count(self, selector: str) -> int:
        """Cuántos elementos matchean el selector (para iterar listas)."""
        ...

    async def is_visible(self, selector: str, *, timeout_ms: int = 1000) -> bool:
        """Chequea visibilidad sin lanzar excepción."""
        ...

    async def get_text(self, selector: str) -> str:
        """Obtiene el textContent del elemento."""
        ...

    async def get_bounding_box(self, selector: str) -> tuple[float, float, float, float] | None:
        """Devuelve (x, y, width, height) del elemento o None si no existe."""
        ...

    # ── Comportamiento de página ────────────────────────────────────────────
    async def emulate_tab_blur(self, *, duration_ms: int) -> None:
        """Dispara visibilitychange='hidden' por X ms (cambio a otra app simulado)."""
        ...

    async def wait(self, ms: int) -> None:
        """Espera exacta. Usar con jitter del caller para evitar patrones."""
        ...


class IRichBrowserDriver(Protocol):
    """Factory de sesiones rich. Driver moderno con primitivas humanas."""

    def session(
        self,
        *,
        proxy: ProxyEndpoint | None,
        fingerprint: Fingerprint,
        storage_state: dict[str, Any] | None = None,
    ) -> AbstractAsyncContextManager[IRichBrowserSession]:
        """Abre una sesión aislada con primitivas humanas."""
        ...

    async def close(self) -> None:
        """Cierra recursos compartidos."""
        ...
