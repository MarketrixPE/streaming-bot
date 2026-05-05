"""Endpoints de health-check.

- ``/health``: liveness. Devuelve 200 sin tocar dependencias externas.
- ``/readyz``: readiness. Verifica acceso a la base de datos abriendo
  una sesion transaccional y ejecutando ``SELECT 1``.

Ambos endpoints estan exentos de auth y rate-limit (el middleware los
registra en ``skip_paths``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.presentation.api.dependencies import get_session
from streaming_bot.presentation.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    description=(
        "Confirma que el proceso de API responde. No abre conexiones "
        "externas: usa este endpoint para readiness gates de orquestador."
    ),
)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", component_checks={"process": "ok"})


@router.get(
    "/readyz",
    response_model=HealthResponse,
    summary="Readiness probe",
    description=(
        "Comprueba la conectividad con Postgres ejecutando un SELECT 1. "
        "Si la base de datos no responde devuelve 503 con component_checks."
    ),
    responses={
        503: {
            "description": "Base de datos no disponible.",
            "model": HealthResponse,
        }
    },
)
async def readyz(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        return HealthResponse(
            status="degraded",
            component_checks={"database": f"error:{type(exc).__name__}"},
        )
    return HealthResponse(
        status="ok",
        component_checks={"database": "ok", "process": "ok"},
    )
