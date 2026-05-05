"""Daemon por modem que escucha URC AT (+CMTI) y persiste SMS al hub.

Despliegue: una instancia por puerto serie via systemd template:
    /etc/systemd/system/sms-hub-modem@.service

Lee continuamente el AT port. Cuando aparece "+CMTI: \"SM\",<idx>" lee
el SMS via AT+CMGR=<idx>, lo parsea (sender + body + timestamp) y lo
inserta en farm_sms_inbox via asyncpg.

NO usa el paquete streaming_bot: standalone para compartmentalizacion.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import sys
from datetime import UTC, datetime
from typing import Any

import asyncpg

try:
    import serial_asyncio  # type: ignore[import-not-found]
except ImportError:
    print("ERROR: pyserial-asyncio requerido. apt install python3-serial-asyncio", file=sys.stderr)
    sys.exit(1)

DATABASE_URL = os.environ["DATABASE_URL"]
SERIAL_PORT = os.environ.get("SERIAL_PORT", "/dev/ttyUSB2")
BAUDRATE = int(os.environ.get("BAUDRATE", "115200"))
IMEI = os.environ["MODEM_IMEI"]

_AT_SET_TEXT_MODE = "AT+CMGF=1\r\n"
_AT_ENABLE_URC = 'AT+CNMI=2,1,0,0,0\r\n'

_CMTI_RE = re.compile(r'\+CMTI:\s*"\w+",\s*(\d+)')
_CMGR_HEADER_RE = re.compile(
    r'\+CMGR:\s*"[^"]*",\s*"(?P<sender>[^"]+)",\s*"[^"]*",\s*"(?P<ts>[^"]+)"',
)


async def main() -> None:
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    reader, writer = await serial_asyncio.open_serial_connection(
        url=SERIAL_PORT, baudrate=BAUDRATE,
    )
    try:
        await _send(writer, _AT_SET_TEXT_MODE)
        await asyncio.sleep(0.5)
        await _send(writer, _AT_ENABLE_URC)
        print(f"[modem {IMEI}] daemon up on {SERIAL_PORT}", flush=True)

        while True:
            line = await _readline(reader)
            if not line:
                continue
            match = _CMTI_RE.search(line)
            if not match:
                continue
            idx = int(match.group(1))
            sms = await _read_sms(reader, writer, idx)
            if sms is None:
                continue
            await _persist_sms(pool, sms)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        await pool.close()


async def _send(writer: asyncio.StreamWriter, command: str) -> None:
    writer.write(command.encode("ascii"))
    await writer.drain()


async def _readline(reader: asyncio.StreamReader) -> str:
    raw = await reader.readline()
    return raw.decode("ascii", errors="ignore").rstrip("\r\n")


async def _read_sms(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    idx: int,
) -> dict[str, Any] | None:
    await _send(writer, f"AT+CMGR={idx}\r\n")
    header: dict[str, str] = {}
    body_lines: list[str] = []
    seen_header = False
    deadline = asyncio.get_event_loop().time() + 10.0
    while asyncio.get_event_loop().time() < deadline:
        line = await _readline(reader)
        if not line:
            continue
        if line.startswith("OK"):
            break
        if line.startswith("ERROR"):
            return None
        match = _CMGR_HEADER_RE.search(line)
        if match:
            header["sender"] = match.group("sender")
            header["ts"] = match.group("ts")
            seen_header = True
            continue
        if seen_header:
            body_lines.append(line)

    # Borramos el SMS para liberar slot SIM (AT+CMGD).
    await _send(writer, f"AT+CMGD={idx}\r\n")
    if not header:
        return None
    return {
        "sender": header["sender"],
        "body": "\n".join(body_lines).strip(),
        "received_at": _parse_cmgr_ts(header.get("ts", "")),
    }


def _parse_cmgr_ts(ts: str) -> datetime:
    """CMGR timestamp ej '24/12/01,18:42:10+04'."""
    if not ts:
        return datetime.now(UTC)
    try:
        date_part, _, time_zone = ts.partition(",")
        time_part = time_zone[:8]  # HH:MM:SS
        return datetime.strptime(
            f"{date_part} {time_part}", "%y/%m/%d %H:%M:%S",
        ).replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(UTC)


async def _persist_sms(pool: asyncpg.Pool, sms: dict[str, Any]) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT sid FROM farm_numbers
                WHERE imei = $1 AND released_at IS NULL AND expires_at > NOW()
                ORDER BY rented_at DESC LIMIT 1
                """,
                IMEI,
            )
            if row is None:
                # SMS no esperado (numero no alquilado). Lo descartamos.
                print(f"[modem {IMEI}] orphan SMS from {sms['sender']}", flush=True)
                return
            await conn.execute(
                """
                INSERT INTO farm_sms_inbox (sid, sender, body, received_at)
                VALUES ($1, $2, $3, $4)
                """,
                row["sid"],
                sms["sender"],
                sms["body"],
                sms["received_at"],
            )
            await conn.execute(
                "UPDATE farm_modems SET last_seen_at = NOW() WHERE imei = $1",
                IMEI,
            )
            print(
                f"[modem {IMEI}] SMS stored sid={row['sid']} sender={sms['sender']}",
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
