"""Driver de modems Quectel (EG25-G / RM500Q-GL) y compatibles AT estandar.

Diseno:
- Una instancia de driver maneja N modems; cada modem tiene su `serial_port` propio
  y un `asyncio.Lock` por `modem.id` para serializar AT commands.
- Las conexiones serial se abren on-demand y se cachean por modem.
- La rotacion de IP usa la secuencia AT+CFUN=4 -> AT+CFUN=1 que detacha y vuelve a
  attachar a la torre, forzando al carrier a re-asignar IP publica.
- La consulta de IP publica se delega a un helper inyectable (`_http_get_via_modem`)
  que abstrae la logica de salir por la interfaz del modem (ip route + iface binding).

NO usamos un proceso por modem porque pyserial-asyncio + locks por id es suficiente:
los AT commands son texto pequeno y la tasa de uso por modem es baja (~3 cuentas/dia).
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import aiohttp
import serial_asyncio

from streaming_bot.domain.modem import Modem
from streaming_bot.infrastructure.modems.at_commands import (
    AT_CFUN_AIRPLANE,
    AT_CFUN_FULL,
    AT_GET_SIGNAL,
    AT_PING,
    AT_RESET,
    is_terminal_line,
    parse_csq,
)

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

# Defaults razonables para Quectel; configurables via constructor.
_DEFAULT_BAUDRATE: int = 115200
_DEFAULT_AT_TIMEOUT_S: float = 10.0
_REATTACH_AFTER_AIRPLANE_S: float = 2.0
_REATTACH_DWELL_S: float = 5.0
_PUBLIC_IP_TIMEOUT_S: float = 10.0
_DEFAULT_PUBLIC_IP_URL: str = "https://api.ipify.org"
_NEWLINE: bytes = b"\r\n"


class HttpViaModem(Protocol):
    """Helper inyectable para HTTP GET sourceando por la interfaz del modem.

    Implementaciones tipicas:
    - InterfaceBinder + aiohttp con `local_addr` apuntando a la IP del modem.
    - Proxy SOCKS5 local del modem (PureSocks5Server) y aiohttp_socks/aiohttp con BasicAuth.

    Mantenemos esto como Protocol para no acoplar el driver a una estrategia concreta.
    """

    async def __call__(self, modem: Modem, url: str) -> str: ...


@dataclass(slots=True)
class _SerialChannel:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter


class QuectelModemDriver:
    """Implementa IModemDriver para modems Quectel y otros con AT estandar.

    Inyectables:
    - `http_get_via_modem`: helper que ejecuta HTTP GET via la NIC del modem.
    - `logger`: structlog BoundLogger.
    """

    def __init__(
        self,
        *,
        logger: BoundLogger,
        http_get_via_modem: HttpViaModem | None = None,
        baudrate: int = _DEFAULT_BAUDRATE,
        at_timeout_seconds: float = _DEFAULT_AT_TIMEOUT_S,
        public_ip_url: str = _DEFAULT_PUBLIC_IP_URL,
    ) -> None:
        self._logger = logger
        self._http_get_via_modem = http_get_via_modem or _default_http_get_via_modem
        self._baudrate = baudrate
        self._at_timeout = at_timeout_seconds
        self._public_ip_url = public_ip_url
        self._channels: dict[str, _SerialChannel] = {}
        self._channels_lock = asyncio.Lock()
        self._command_locks: dict[str, asyncio.Lock] = {}
        self._command_locks_lock = asyncio.Lock()

    async def health_check(self, modem: Modem) -> bool:
        """Health check ligero: AT ping + medicion de senal."""
        try:
            response = await self.send_at_command(modem, AT_PING)
        except (TimeoutError, OSError) as exc:
            self._logger.warning("modem_health_check_failed", modem_id=modem.id, error=str(exc))
            return False
        if "OK" not in response:
            return False
        try:
            await self.get_signal_strength(modem)
        except (TimeoutError, OSError):
            return False
        return True

    async def rotate_ip(self, modem: Modem) -> str | None:
        """Fuerza reattach a la torre via CFUN=4 -> CFUN=1.

        Por que el ciclo airplane-on/off: CFUN=0/1 (full reset radio) es mas lento
        y a veces requiere PIN; CFUN=4 (rx-off-tx-off) preserva la SIM session y es
        suficiente para que el carrier asigne nueva IP publica al re-attach.
        """
        try:
            await self.send_at_command(modem, AT_CFUN_AIRPLANE)
            await asyncio.sleep(_REATTACH_AFTER_AIRPLANE_S)
            await self.send_at_command(modem, AT_CFUN_FULL)
        except (TimeoutError, OSError) as exc:
            self._logger.error("modem_rotate_failed", modem_id=modem.id, error=str(exc))
            return None
        # Esperamos a que el modem complete attach + obtenga IP del carrier.
        await asyncio.sleep(_REATTACH_DWELL_S)
        return await self.get_public_ip(modem)

    async def get_public_ip(self, modem: Modem) -> str | None:
        """HTTP GET a api.ipify.org sourceado por la NIC del modem."""
        try:
            return await asyncio.wait_for(
                self._http_get_via_modem(modem, self._public_ip_url),
                timeout=_PUBLIC_IP_TIMEOUT_S,
            )
        except (TimeoutError, aiohttp.ClientError, OSError) as exc:
            self._logger.warning("modem_get_public_ip_failed", modem_id=modem.id, error=str(exc))
            return None

    async def get_signal_strength(self, modem: Modem) -> int:
        """Devuelve dBm. Si el modem no reporta senal devolvemos -120 (suelo)."""
        response = await self.send_at_command(modem, AT_GET_SIGNAL)
        dbm = parse_csq(response)
        if dbm is None:
            self._logger.warning("modem_signal_unavailable", modem_id=modem.id)
            return -120
        return dbm

    async def reset(self, modem: Modem) -> None:
        """Reset duro (AT+CFUN=1,1). El modem se cuelga ~30s tras esto."""
        await self.send_at_command(modem, AT_RESET)
        # No esperamos respuesta OK porque el modem se reinicia y cierra el puerto.
        await self._close_channel(modem)

    async def send_at_command(self, modem: Modem, command: str) -> str:
        """Envia un AT command y devuelve la respuesta hasta OK/ERROR.

        Garantiza serializacion por modem.id via asyncio.Lock para evitar mezclar
        respuestas entre comandos concurrentes (el modem es half-duplex en banda AT).
        """
        lock = await self._get_command_lock(modem.id)
        async with lock:
            channel = await self._get_channel(modem)
            payload = command.encode("ascii") + _NEWLINE
            channel.writer.write(payload)
            await channel.writer.drain()
            return await self._read_until_terminator(channel.reader)

    # ----------------------------- canales serial -----------------------------

    async def _get_channel(self, modem: Modem) -> _SerialChannel:
        async with self._channels_lock:
            cached = self._channels.get(modem.id)
            if cached is not None:
                return cached
            reader, writer = await serial_asyncio.open_serial_connection(
                url=modem.hardware.serial_port,
                baudrate=self._baudrate,
            )
            channel = _SerialChannel(reader=reader, writer=writer)
            self._channels[modem.id] = channel
            return channel

    async def _close_channel(self, modem: Modem) -> None:
        async with self._channels_lock:
            channel = self._channels.pop(modem.id, None)
        if channel is None:
            return
        channel.writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await channel.writer.wait_closed()

    async def _get_command_lock(self, modem_id: str) -> asyncio.Lock:
        async with self._command_locks_lock:
            lock = self._command_locks.get(modem_id)
            if lock is None:
                lock = asyncio.Lock()
                self._command_locks[modem_id] = lock
            return lock

    async def _read_until_terminator(self, reader: asyncio.StreamReader) -> str:
        """Lee lineas del modem hasta encontrar OK / ERROR / +CME ERROR."""
        deadline = asyncio.get_event_loop().time() + self._at_timeout
        buffer: list[str] = []
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError("AT command timed out waiting for terminator")
            try:
                line_bytes = await asyncio.wait_for(reader.readline(), timeout=remaining)
            except TimeoutError as exc:
                raise TimeoutError("AT command timed out") from exc
            if not line_bytes:
                # EOF inesperado del puerto serial.
                raise OSError("modem serial channel closed unexpectedly")
            line = line_bytes.decode("ascii", errors="replace").rstrip("\r\n")
            buffer.append(line)
            if is_terminal_line(line):
                return "\n".join(buffer)


async def _default_http_get_via_modem(modem: Modem, url: str) -> str:  # noqa: ARG001
    """Implementacion por defecto: GET directo a `url`.

    `modem` se ignora aqui de forma intencional. Para un setup productivo se debe
    inyectar un `HttpViaModem` real (ej. via LinuxInterfaceBinder + aiohttp con
    `local_addr`, o via el proxy SOCKS5 local del modem). Mantenemos esta version
    como fallback para que el driver sea utilizable en dev/tests sin red real.
    """
    timeout = aiohttp.ClientTimeout(total=_PUBLIC_IP_TIMEOUT_S)
    async with aiohttp.ClientSession(timeout=timeout) as session, session.get(url) as response:
        response.raise_for_status()
        text = await response.text()
        return text.strip()
