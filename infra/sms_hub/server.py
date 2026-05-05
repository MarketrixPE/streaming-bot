"""SMS hub FastAPI server.

Despliegue: ESTE archivo vive EN el nodo de granja (Lithuania/Bulgaria/
Vietnam). Su responsabilidad es exponer una API tipo 5SIM-lite contra el
pool de modems fisicos. Persiste numeros activos + SMS entrantes en
Postgres (tablas `farm_numbers` y `farm_sms_inbox`).

NO depende del paquete streaming_bot: vive standalone para poder
desplegarse SIN compartir secretos del control plane (compartmentalizacion
de OPSEC: si alguien gana root al SMS hub, NO obtiene credenciales de
banking/distribuidor).

Ejecucion:
    uvicorn server:app --host 0.0.0.0 --port 8090

Env vars:
    SMS_HUB_TOKEN       Bearer token compartido con el control plane.
    DATABASE_URL        postgres async (asyncpg).
    LONG_POLL_MAX_S     Tiempo max de long-poll por request (default 25).
"""

from __future__ import annotations

import asyncio
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import asyncpg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from pydantic import BaseModel

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/sms_hub")
SMS_HUB_TOKEN = os.environ["SMS_HUB_TOKEN"]
LONG_POLL_MAX_S = float(os.environ.get("LONG_POLL_MAX_S", "25"))
RENT_TTL_MINUTES = int(os.environ.get("RENT_TTL_MINUTES", "30"))

app = FastAPI(title="streaming-bot sms-hub", version="1.0")
_pool: asyncpg.Pool | None = None


# ── Schemas ──────────────────────────────────────────────────────────────


class RentRequest(BaseModel):
    country: str  # ISO alpha-2


class RentResponse(BaseModel):
    sid: str
    e164: str
    country: str
    expires_at: datetime


class SmsResponse(BaseModel):
    sid: str
    sender: str
    body: str
    received_at: datetime


class ModemStatus(BaseModel):
    imei: str
    iccid: str
    operator: str
    country: str
    is_busy: bool
    last_seen: datetime | None
    flagged_count: int


# ── Auth ─────────────────────────────────────────────────────────────────


def _verify_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, SMS_HUB_TOKEN):
        raise HTTPException(status_code=403, detail="invalid token")


# ── Lifecycle ────────────────────────────────────────────────────────────


@app.on_event("startup")
async def _startup() -> None:
    global _pool  # noqa: PLW0603
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    await _ensure_schema()


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _pool is not None:
        await _pool.close()


async def _ensure_schema() -> None:
    assert _pool is not None
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS farm_modems (
                imei         TEXT PRIMARY KEY,
                iccid        TEXT NOT NULL,
                operator     TEXT NOT NULL,
                country      TEXT NOT NULL,
                e164         TEXT NOT NULL,
                serial_port  TEXT NOT NULL,
                last_seen_at TIMESTAMPTZ,
                flagged_count INT NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS farm_numbers (
                sid          TEXT PRIMARY KEY,
                imei         TEXT NOT NULL REFERENCES farm_modems(imei),
                e164         TEXT NOT NULL,
                country      TEXT NOT NULL,
                rented_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at   TIMESTAMPTZ NOT NULL,
                released_at  TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS idx_farm_numbers_active
                ON farm_numbers (released_at, expires_at)
                WHERE released_at IS NULL;
            CREATE TABLE IF NOT EXISTS farm_sms_inbox (
                id           BIGSERIAL PRIMARY KEY,
                sid          TEXT NOT NULL REFERENCES farm_numbers(sid) ON DELETE CASCADE,
                sender       TEXT NOT NULL,
                body         TEXT NOT NULL,
                received_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                consumed_at  TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS idx_sms_unconsumed
                ON farm_sms_inbox (sid, received_at)
                WHERE consumed_at IS NULL;
            """,
        )


# ── Endpoints ────────────────────────────────────────────────────────────


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/numbers/rent", response_model=RentResponse, dependencies=[Depends(_verify_token)])
async def rent_number(request: RentRequest) -> RentResponse:
    assert _pool is not None
    sid = secrets.token_urlsafe(12)
    expires_at = datetime.now(UTC) + timedelta(minutes=RENT_TTL_MINUTES)
    async with _pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT m.imei, m.e164
                FROM farm_modems m
                WHERE m.country = $1
                  AND NOT EXISTS (
                      SELECT 1 FROM farm_numbers n
                      WHERE n.imei = m.imei
                        AND n.released_at IS NULL
                        AND n.expires_at > NOW()
                  )
                  AND m.flagged_count < 5
                ORDER BY COALESCE(m.last_seen_at, '1970-01-01') DESC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                request.country.upper(),
            )
            if row is None:
                raise HTTPException(status_code=409, detail="no_modem_available")

            await conn.execute(
                """
                INSERT INTO farm_numbers (sid, imei, e164, country, expires_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                sid,
                row["imei"],
                row["e164"],
                request.country.upper(),
                expires_at,
            )
    return RentResponse(
        sid=sid,
        e164=row["e164"],
        country=request.country.upper(),
        expires_at=expires_at,
    )


@app.delete("/numbers/{sid}", dependencies=[Depends(_verify_token)])
async def release_number(sid: str) -> Response:
    assert _pool is not None
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE farm_numbers SET released_at = NOW() WHERE sid = $1 AND released_at IS NULL",
            sid,
        )
    return Response(status_code=204)


@app.get(
    "/numbers/{sid}/sms",
    response_model=SmsResponse | None,
    dependencies=[Depends(_verify_token)],
)
async def wait_for_sms(
    sid: str,
    wait_seconds: float = Query(default=10.0, ge=0.0, le=LONG_POLL_MAX_S),
    contains: str = Query(default=""),
) -> Response:
    """Long-poll: bloquea hasta `wait_seconds` o hasta que llegue un SMS."""
    assert _pool is not None
    deadline = asyncio.get_event_loop().time() + wait_seconds
    while True:
        async with _pool.acquire() as conn:
            sms_row = await conn.fetchrow(
                """
                SELECT id, sender, body, received_at
                FROM farm_sms_inbox
                WHERE sid = $1
                  AND consumed_at IS NULL
                  AND ($2 = '' OR body LIKE '%' || $2 || '%')
                ORDER BY received_at ASC
                LIMIT 1
                """,
                sid,
                contains,
            )
            if sms_row is not None:
                await conn.execute(
                    "UPDATE farm_sms_inbox SET consumed_at = NOW() WHERE id = $1",
                    sms_row["id"],
                )
                return Response(
                    media_type="application/json",
                    content=SmsResponse(
                        sid=sid,
                        sender=sms_row["sender"],
                        body=sms_row["body"],
                        received_at=sms_row["received_at"],
                    ).model_dump_json(),
                )
        if asyncio.get_event_loop().time() >= deadline:
            return Response(status_code=204)
        await asyncio.sleep(1.0)


@app.get(
    "/modems",
    response_model=list[ModemStatus],
    dependencies=[Depends(_verify_token)],
)
async def list_modems() -> list[ModemStatus]:
    assert _pool is not None
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                m.imei,
                m.iccid,
                m.operator,
                m.country,
                m.last_seen_at,
                m.flagged_count,
                EXISTS (
                    SELECT 1 FROM farm_numbers n
                    WHERE n.imei = m.imei
                      AND n.released_at IS NULL
                      AND n.expires_at > NOW()
                ) AS is_busy
            FROM farm_modems m
            ORDER BY m.country, m.imei
            """,
        )
    return [
        ModemStatus(
            imei=row["imei"],
            iccid=row["iccid"],
            operator=row["operator"],
            country=row["country"],
            is_busy=row["is_busy"],
            last_seen=row["last_seen_at"],
            flagged_count=row["flagged_count"],
        )
        for row in rows
    ]
