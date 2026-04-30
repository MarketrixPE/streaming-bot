"""Puerto para drivers de browser. Abstrae Playwright/Selenium/etc.

Sprint 2: ver también `domain/ports/browser_rich.py` para `IRichBrowserSession`,
que extiende este protocolo con primitivas humanas (mouse Bezier, type con
delays, scroll suave) que consume el `IBehaviorEngine` para componer los
45 behaviors. Drivers modernos (Camoufox) implementan el contrato extendido.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, runtime_checkable

from streaming_bot.domain.value_objects import Fingerprint, ProxyEndpoint


@runtime_checkable
class IBrowserSession(Protocol):
    """Sesión activa de browser. Abstrae el `Page` de Playwright.

    Las implementaciones deben proveer auto-wait y manejo de timeouts.
    """

    async def goto(self, url: str, *, wait_until: str = "networkidle") -> None: ...

    async def fill(self, selector: str, value: str) -> None: ...

    async def click(self, selector: str) -> None: ...

    async def wait_for_selector(self, selector: str, *, timeout_ms: int = 30000) -> None: ...

    async def evaluate(self, expression: str) -> Any: ...

    async def screenshot(self, path: str) -> None: ...

    async def content(self) -> str: ...

    async def storage_state(self) -> dict[str, Any]: ...


class IBrowserDriver(Protocol):
    """Factory de sesiones de browser."""

    def session(
        self,
        *,
        proxy: ProxyEndpoint | None,
        fingerprint: Fingerprint,
        storage_state: dict[str, Any] | None = None,
    ) -> AbstractAsyncContextManager[IBrowserSession]:
        """Abre una sesión aislada y la cierra al salir del contexto.

        Args:
            proxy: proxy a usar; None = conexión directa.
            fingerprint: huella coherente que el browser debe presentar.
            storage_state: cookies/localStorage previos para skip de login.
        """
        ...

    async def close(self) -> None:
        """Cierra recursos compartidos (browser, playwright)."""
        ...
