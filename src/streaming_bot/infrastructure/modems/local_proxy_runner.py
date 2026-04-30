"""Runner de proxies SOCKS5 locales por modem.

Estrategia:
- Por defecto arrancamos un PureSocks5Server (puro Python, sin dependencias).
- Si esta disponible un binario externo (`microsocks` o `dante-server`) lo usamos
  como upgrade de performance, pero no es requisito.
- Cada modem tiene un puerto local distinto (10001..10030).
- El proxy se sourcea a la IP local del modem (bind_address) para que el kernel
  enrute el trafico saliente por la interfaz movil correspondiente.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

from streaming_bot.infrastructure.modems.pure_socks5 import PureSocks5Server

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

# Binarios externos que aceptamos como upgrade opcional.
_EXTERNAL_BINARIES: tuple[str, ...] = ("microsocks", "dante-server")


@dataclass(slots=True)
class _RunningProxy:
    """Maneja el ciclo de vida de un proxy local activo."""

    port: int
    bind_iface: str
    pure_server: PureSocks5Server | None = None
    external_process: asyncio.subprocess.Process | None = None


class DanteProxyRunner:
    """Arranca/detiene proxies SOCKS5 locales por modem.

    Pensado para inyectarse via DI; mantiene estado interno del set de proxies activos
    para garantizar idempotencia y permitir un shutdown coordinado.
    """

    def __init__(
        self,
        *,
        logger: BoundLogger,
        prefer_external: bool = False,
        bind_host: str = "127.0.0.1",
    ) -> None:
        self._logger = logger
        self._prefer_external = prefer_external
        self._bind_host = bind_host
        self._proxies: dict[int, _RunningProxy] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        port: int,
        bind_iface: str,
        *,
        bind_address: str | None = None,
    ) -> None:
        """Arranca un proxy en `port` que sale por `bind_iface`/`bind_address`."""
        async with self._lock:
            if port in self._proxies:
                return
            running = _RunningProxy(port=port, bind_iface=bind_iface)
            external_bin = self._select_external_binary() if self._prefer_external else None
            if external_bin is not None:
                running.external_process = await self._start_external(
                    external_bin,
                    port,
                    bind_iface,
                )
                self._logger.info(
                    "local_proxy_started_external",
                    port=port,
                    iface=bind_iface,
                    binary=external_bin,
                )
            else:
                running.pure_server = await self._start_pure(port, bind_address)
                self._logger.info(
                    "local_proxy_started_pure",
                    port=port,
                    iface=bind_iface,
                    bind_address=bind_address,
                )
            self._proxies[port] = running

    async def stop(self, port: int) -> None:
        """Detiene el proxy del puerto. No-op si no existe."""
        async with self._lock:
            running = self._proxies.pop(port, None)
            if running is None:
                return
            if running.pure_server is not None:
                await running.pure_server.stop()
            if running.external_process is not None:
                await self._stop_external(running.external_process)
            self._logger.info("local_proxy_stopped", port=port, iface=running.bind_iface)

    async def stop_all(self) -> None:
        """Detiene todos los proxies del runner."""
        async with self._lock:
            ports = list(self._proxies.keys())
        for port in ports:
            await self.stop(port)

    def is_running(self, port: int) -> bool:
        return port in self._proxies

    async def _start_pure(self, port: int, bind_address: str | None) -> PureSocks5Server:
        # Decision: el proxy puro Python escucha solo en localhost para no exponerlo.
        server = PureSocks5Server(
            host=self._bind_host,
            port=port,
            bind_address=bind_address,
            logger=self._logger,
        )
        await server.start()
        return server

    @staticmethod
    def _select_external_binary() -> str | None:
        for name in _EXTERNAL_BINARIES:
            if shutil.which(name) is not None:
                return name
        return None

    async def _start_external(
        self,
        binary: str,
        port: int,
        bind_iface: str,
    ) -> asyncio.subprocess.Process:
        # Cada binario tiene su CLI; soportamos los dos mas comunes.
        if binary == "microsocks":
            args = ["-i", self._bind_host, "-p", str(port)]
        elif binary == "dante-server":
            # dante-server requiere config file; aqui lo arrancamos en modo basico.
            args = ["-D", "-f", f"/etc/dante-{port}.conf"]
        else:  # pragma: no cover - defensiva
            raise RuntimeError(f"binario externo no soportado: {binary}")
        self._logger.debug(
            "external_proxy_spawn",
            binary=binary,
            args=args,
            iface=bind_iface,
        )
        return await asyncio.create_subprocess_exec(
            binary,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    @staticmethod
    async def _stop_external(proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except TimeoutError:
            proc.kill()
            await proc.wait()
