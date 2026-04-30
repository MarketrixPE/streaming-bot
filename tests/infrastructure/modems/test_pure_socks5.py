"""Smoke test del PureSocks5Server: handshake + CONNECT contra echo server local."""

from __future__ import annotations

import asyncio
import socket
import struct

import pytest
from structlog.stdlib import BoundLogger

from streaming_bot.infrastructure.modems.pure_socks5 import (
    ATYP_DOMAIN,
    ATYP_IPV4,
    AUTH_NONE,
    CMD_CONNECT,
    REP_SUCCESS,
    SOCKS5_VERSION,
    PureSocks5Server,
)


def _free_port() -> int:
    """Reserva un puerto local efimero para el test."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _start_echo_server() -> tuple[asyncio.base_events.Server, int]:
    """Servidor TCP que devuelve el primer chunk recibido."""

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.read(1024)
        writer.write(data)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handler, "127.0.0.1", 0)
    port = int(server.sockets[0].getsockname()[1])
    return server, port


class TestPureSocks5Server:
    async def test_connect_via_proxy_to_echo(self, silent_logger: BoundLogger) -> None:
        echo_server, echo_port = await _start_echo_server()
        proxy_port = _free_port()
        proxy = PureSocks5Server(port=proxy_port, logger=silent_logger)
        await proxy.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            # Greeting: VER=5, NMETHODS=1, METHOD=NO_AUTH.
            writer.write(bytes([SOCKS5_VERSION, 1, AUTH_NONE]))
            await writer.drain()
            greeting = await reader.readexactly(2)
            assert greeting[0] == SOCKS5_VERSION
            assert greeting[1] == AUTH_NONE
            # Request: VER=5, CMD=CONNECT, RSV=0, ATYP=IPv4, DST.ADDR=127.0.0.1, DST.PORT.
            request = bytes(
                [SOCKS5_VERSION, CMD_CONNECT, 0x00, ATYP_IPV4, 127, 0, 0, 1],
            ) + struct.pack("!H", echo_port)
            writer.write(request)
            await writer.drain()
            reply = await reader.readexactly(10)
            assert reply[0] == SOCKS5_VERSION
            assert reply[1] == REP_SUCCESS
            # Tunel establecido: enviamos payload y esperamos echo.
            payload = b"hello-pure-socks5"
            writer.write(payload)
            await writer.drain()
            received = await asyncio.wait_for(reader.read(len(payload)), timeout=2.0)
            assert received == payload
            writer.close()
            await writer.wait_closed()
        finally:
            await proxy.stop()
            echo_server.close()
            await echo_server.wait_closed()

    async def test_unsupported_command_returns_error(self, silent_logger: BoundLogger) -> None:
        proxy_port = _free_port()
        proxy = PureSocks5Server(port=proxy_port, logger=silent_logger)
        await proxy.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            writer.write(bytes([SOCKS5_VERSION, 1, AUTH_NONE]))
            await writer.drain()
            await reader.readexactly(2)
            # CMD=0x02 (BIND) no soportado.
            writer.write(
                bytes([SOCKS5_VERSION, 0x02, 0x00, ATYP_DOMAIN, 0x09])
                + b"localhost"
                + struct.pack("!H", 80),
            )
            await writer.drain()
            reply = await reader.readexactly(10)
            assert reply[0] == SOCKS5_VERSION
            assert reply[1] != REP_SUCCESS
            writer.close()
            await writer.wait_closed()
        finally:
            await proxy.stop()

    async def test_rejects_non_socks5_version(self, silent_logger: BoundLogger) -> None:
        proxy_port = _free_port()
        proxy = PureSocks5Server(port=proxy_port, logger=silent_logger)
        await proxy.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            writer.write(bytes([0x04, 1, AUTH_NONE]))  # SOCKS4, no SOCKS5
            await writer.drain()
            with pytest.raises((asyncio.IncompleteReadError, ConnectionError)):
                await reader.readexactly(2)
            writer.close()
            await writer.wait_closed()
        finally:
            await proxy.stop()
