"""MixedBrowserDriver: rota IBrowserDriver primario / secundario.

El stealth stack 2026 ganador (informe sub-agente B) usa una mezcla
heterogenea de browser engines: Patchright (Chromium patched) en ~70%
de las sesiones y Camoufox (Firefox stealth) en ~30%. El share emula la
distribucion real de Chrome / Firefox en internet y reduce la "uniformidad
binaria" que el antifraud puede correlacionar.

Esta clase implementa IBrowserDriver agregando dos drivers concretos y
delegando cada session() al elegido segun una distribucion ponderada.

Si solo se quiere Patchright o solo Camoufox, basta con weight 100/0.
"""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog

from streaming_bot.domain.ports.browser import IBrowserDriver, IBrowserSession
from streaming_bot.domain.value_objects import Fingerprint, ProxyEndpoint

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class MixedBrowserDriver(IBrowserDriver):
    """Combina dos drivers con un peso (default 70 primario / 30 secundario)."""

    def __init__(
        self,
        *,
        primary: IBrowserDriver,
        secondary: IBrowserDriver,
        primary_weight: int = 70,
        secondary_weight: int = 30,
    ) -> None:
        if primary_weight < 0 or secondary_weight < 0:
            raise ValueError("pesos no negativos")
        if primary_weight + secondary_weight == 0:
            raise ValueError("la suma de pesos debe ser > 0")
        self._primary = primary
        self._secondary = secondary
        self._primary_weight = primary_weight
        self._secondary_weight = secondary_weight
        self._log = structlog.get_logger("mixed_browser_driver")
        self._sessions_by_engine: dict[str, int] = {"primary": 0, "secondary": 0}

    async def start(self) -> None:
        # Solo arrancamos los que tengan start() (PlaywrightDriver/PatchrightDriver lo tienen,
        # CamoufoxDriver es lazy y no requiere start).
        for driver in (self._primary, self._secondary):
            start_fn = getattr(driver, "start", None)
            if callable(start_fn):
                await start_fn()

    async def close(self) -> None:
        for driver in (self._primary, self._secondary):
            close_fn = getattr(driver, "close", None)
            if callable(close_fn):
                await close_fn()

    @asynccontextmanager
    async def session(
        self,
        *,
        proxy: ProxyEndpoint | None,
        fingerprint: Fingerprint,
        storage_state: dict[str, Any] | None = None,
    ) -> AsyncIterator[IBrowserSession]:
        engine, driver = self._pick_engine(fingerprint)
        self._sessions_by_engine[engine] += 1
        self._log.debug(
            "browser_engine_selected",
            engine=engine,
            country=fingerprint.country.value,
            ua_fragment=fingerprint.user_agent[:30],
        )
        async with driver.session(
            proxy=proxy,
            fingerprint=fingerprint,
            storage_state=storage_state,
        ) as page:
            yield page

    def _pick_engine(
        self,
        fingerprint: Fingerprint,
    ) -> tuple[str, IBrowserDriver]:
        """Selecciona engine consistente con el UA del fingerprint cuando posible.

        Si el UA es Firefox, preferimos Camoufox (secundario) para coherencia.
        Si es Chrome/Safari, usamos Patchright (primario). En ausencia de match
        claro, ponderamos por (primary_weight, secondary_weight).
        """
        ua = fingerprint.user_agent
        if "Firefox/" in ua:
            return "secondary", self._secondary
        if "Chrome/" in ua or "Version/" in ua:
            # Chrome o Safari: usamos primario (Patchright).
            return "primary", self._primary
        # Fallback ponderado (sin UA reconocible, no deberia ocurrir).
        total = self._primary_weight + self._secondary_weight
        pick = secrets.randbelow(total)
        if pick < self._primary_weight:
            return "primary", self._primary
        return "secondary", self._secondary

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._sessions_by_engine)
