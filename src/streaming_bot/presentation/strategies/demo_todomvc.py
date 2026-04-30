"""Estrategia de demo contra TodoMVC público (https://demo.playwright.dev/todomvc).

Sirve para validar la pipeline completa SIN tocar Spotify ni ningún sitio
con ToS restrictivos. Para añadir un sitio nuevo: crear otra estrategia
en este mismo paquete y registrarla en la CLI.
"""

from __future__ import annotations

import asyncio

from streaming_bot.application.stream_song import ISiteStrategy
from streaming_bot.domain.entities import Account
from streaming_bot.domain.ports.browser import IBrowserSession


class DemoTodoMVCStrategy(ISiteStrategy):
    """Demo: añade un TODO con el username y espera N segundos."""

    async def is_logged_in(self, page: IBrowserSession) -> bool:  # noqa: ARG002
        return True

    async def login(
        self,
        page: IBrowserSession,  # noqa: ARG002
        account: Account,  # noqa: ARG002
    ) -> None:
        return

    async def perform_action(
        self,
        page: IBrowserSession,
        target_url: str,
        listen_seconds: int,
    ) -> None:
        await page.goto(target_url, wait_until="domcontentloaded")
        await page.wait_for_selector(".new-todo")
        await page.fill(".new-todo", "sb-demo-todo")
        await page.evaluate(
            "() => { const i = document.querySelector('.new-todo'); "
            "i.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' })); }",
        )
        await asyncio.sleep(min(listen_seconds, 5))
