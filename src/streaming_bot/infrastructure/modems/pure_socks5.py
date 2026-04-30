"""Servidor SOCKS5 minimal en puro Python (RFC 1928 / RFC 1929 simplificados).

Diseno:
- Usamos asyncio.start_server para evitar dependencias externas en mac/dev.
- Soportamos auth NO_AUTH (0x00) y USER/PASSWORD (0x02). En localhost se acepta sin auth.
- Solo CONNECT (CMD=1). UDP_ASSOCIATE/BIND quedan fuera (no los necesita un browser).
- Direcciones aceptadas: IPv4 (ATYP=1) y DOMAIN (ATYP=3); IPv6 fuera de scope.
- Si se pasa `bind_address`, la conexion saliente se hace sourceada a esa IP local
  (uno de los wwan*/ppp* del modem) -> el trafico sale por la interfaz correcta.

No es un proxy de produccion: no maneja flow control sofisticado ni metricas.
Para los tests basta con que reenvie bytes en ambas direcciones.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import socket
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

# Constantes del protocolo SOCKS5.
SOCKS5_VERSION: int = 0x05
AUTH_NONE: int = 0x00
AUTH_USERPASS: int = 0x02
AUTH_NO_ACCEPTABLE: int = 0xFF

CMD_CONNECT: int = 0x01

ATYP_IPV4: int = 0x01
ATYP_DOMAIN: int = 0x03
ATYP_IPV6: int = 0x04

REP_SUCCESS: int = 0x00
REP_GENERAL_FAILURE: int = 0x01
REP_NETWORK_UNREACHABLE: int = 0x03
REP_HOST_UNREACHABLE: int = 0x04
REP_CONNECTION_REFUSED: int = 0x05
REP_COMMAND_NOT_SUPPORTED: int = 0x07
REP_ADDR_TYPE_NOT_SUPPORTED: int = 0x08

_BUFFER_SIZE: int = 64 * 1024
_REMOTE_CONNECT_TIMEOUT: float = 15.0


@dataclass(frozen=True, slots=True)
class Socks5Credentials:
    """Credenciales user/pass opcionales (None = sin auth)."""

    username: str
    password: str


class PureSocks5Server:
    """Servidor SOCKS5 asyncio que ejecuta un asyncio.start_server por modem.

    `bind_address` permite que las conexiones salientes se ejecuten desde una IP
    local concreta (la IP de la interfaz wwan/ppp del modem). El kernel + las
    reglas `ip rule` previas garantizan que ese trafico salga por esa NIC.
    """

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int,
        bind_address: str | None = None,
        require_auth: bool = False,
        credentials: Socks5Credentials | None = None,
        logger: BoundLogger | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._bind_address = bind_address
        self._require_auth = require_auth
        self._credentials = credentials
        self._logger = logger
        self._server: asyncio.base_events.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self._host, self._port)
        if self._logger is not None:
            self._logger.info("socks5_started", host=self._host, port=self._port)

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        if self._logger is not None:
            self._logger.info("socks5_stopped", port=self._port)

    @property
    def port(self) -> int:
        return self._port

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        # Handshake -> auth -> request -> tunel bidireccional.
        try:
            if not await self._negotiate_auth(reader, writer):
                await _safe_close(writer)
                return
            await self._handle_request(reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as exc:
            if self._logger is not None:
                self._logger.warning("socks5_client_error", error=str(exc))
        finally:
            await _safe_close(writer)

    async def _negotiate_auth(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> bool:
        header = await reader.readexactly(2)
        version, n_methods = header[0], header[1]
        if version != SOCKS5_VERSION:
            return False
        methods = await reader.readexactly(n_methods)
        if self._require_auth and AUTH_USERPASS in methods:
            writer.write(bytes([SOCKS5_VERSION, AUTH_USERPASS]))
            await writer.drain()
            return await self._userpass_auth(reader, writer)
        if AUTH_NONE in methods and not self._require_auth:
            writer.write(bytes([SOCKS5_VERSION, AUTH_NONE]))
            await writer.drain()
            return True
        writer.write(bytes([SOCKS5_VERSION, AUTH_NO_ACCEPTABLE]))
        await writer.drain()
        return False

    async def _userpass_auth(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> bool:
        ver = (await reader.readexactly(1))[0]
        if ver != 0x01:
            writer.write(bytes([0x01, 0x01]))
            await writer.drain()
            return False
        ulen = (await reader.readexactly(1))[0]
        username = (await reader.readexactly(ulen)).decode("utf-8", errors="replace")
        plen = (await reader.readexactly(1))[0]
        password = (await reader.readexactly(plen)).decode("utf-8", errors="replace")
        ok = (
            self._credentials is not None
            and username == self._credentials.username
            and password == self._credentials.password
        )
        writer.write(bytes([0x01, 0x00 if ok else 0x01]))
        await writer.drain()
        return ok

    async def _handle_request(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        header = await reader.readexactly(4)
        version, cmd, _rsv, atyp = header[0], header[1], header[2], header[3]
        if version != SOCKS5_VERSION:
            await _reply(writer, REP_GENERAL_FAILURE)
            return
        if cmd != CMD_CONNECT:
            await _reply(writer, REP_COMMAND_NOT_SUPPORTED)
            return

        host = await self._read_destination_address(reader, atyp)
        if host is None:
            await _reply(writer, REP_ADDR_TYPE_NOT_SUPPORTED)
            return
        port = struct.unpack("!H", await reader.readexactly(2))[0]

        try:
            remote_reader, remote_writer = await self._open_remote(host, port)
        except (TimeoutError, OSError):
            await _reply(writer, REP_HOST_UNREACHABLE)
            return

        # Confirmamos exito antes de iniciar el pipe; BND.ADDR/PORT zero-fill.
        await _reply(writer, REP_SUCCESS)
        try:
            await _pipe(reader, writer, remote_reader, remote_writer)
        finally:
            await _safe_close(remote_writer)

    @staticmethod
    async def _read_destination_address(
        reader: asyncio.StreamReader,
        atyp: int,
    ) -> str | None:
        if atyp == ATYP_IPV4:
            raw = await reader.readexactly(4)
            return str(ipaddress.IPv4Address(raw))
        if atyp == ATYP_DOMAIN:
            length = (await reader.readexactly(1))[0]
            return (await reader.readexactly(length)).decode("ascii", errors="replace")
        if atyp == ATYP_IPV6:
            raw = await reader.readexactly(16)
            return str(ipaddress.IPv6Address(raw))
        return None

    async def _open_remote(
        self,
        host: str,
        port: int,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        # Sourceamos la conexion saliente a `bind_address` para forzar salida por la NIC del modem.
        local_addr: tuple[str, int] | None = None
        if self._bind_address is not None:
            local_addr = (self._bind_address, 0)
        return await asyncio.wait_for(
            asyncio.open_connection(
                host=host,
                port=port,
                local_addr=local_addr,
                family=socket.AF_UNSPEC,
            ),
            timeout=_REMOTE_CONNECT_TIMEOUT,
        )


async def _reply(writer: asyncio.StreamWriter, rep_code: int) -> None:
    """Envia respuesta SOCKS5 con BND.ADDR=0.0.0.0:0 (ignorado por clientes CONNECT)."""
    writer.write(bytes([SOCKS5_VERSION, rep_code, 0x00, ATYP_IPV4, 0, 0, 0, 0, 0, 0]))
    await writer.drain()


async def _pipe(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    remote_reader: asyncio.StreamReader,
    remote_writer: asyncio.StreamWriter,
) -> None:
    """Reenvio bidireccional cliente <-> remoto hasta EOF/error."""

    async def _copy(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        try:
            while True:
                chunk = await src.read(_BUFFER_SIZE)
                if not chunk:
                    break
                dst.write(chunk)
                await dst.drain()
        except (ConnectionError, OSError):
            return
        finally:
            await _safe_close(dst)

    await asyncio.gather(
        _copy(client_reader, remote_writer),
        _copy(remote_reader, client_writer),
        return_exceptions=True,
    )


async def _safe_close(writer: asyncio.StreamWriter) -> None:
    """Cierra un StreamWriter ignorando errores benignos en sockets ya rotos."""
    if writer.is_closing():
        return
    with contextlib.suppress(ConnectionError, OSError):
        writer.close()
        await writer.wait_closed()
