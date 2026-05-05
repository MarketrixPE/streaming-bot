"""Router /v1 jobs y sesiones.

En v1 unificamos los conceptos: cada SessionRecord representa un job
ejecutado por el bot. Cuando el queue Temporal externo se exponga en
v2 introduciremos un router /v2/jobs separado.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.history import SessionRecord
from streaming_bot.domain.ports import ISessionRecordRepository
from streaming_bot.infrastructure.persistence.postgres.models.history import (
    SessionRecordModel,
)
from streaming_bot.infrastructure.persistence.postgres.repos.mappers import (
    to_domain_session_record,
)
from streaming_bot.presentation.api.dependencies import (
    get_session,
    get_session_record_repository,
    require_role,
)
from streaming_bot.presentation.api.errors import NotFoundError
from streaming_bot.presentation.api.routers._pagination import MAX_LIMIT, paginate
from streaming_bot.presentation.api.schemas import JobDTO, PaginatedResponse

router = APIRouter(
    prefix="/v1",
    tags=["jobs"],
    dependencies=[Depends(require_role("viewer", "operator", "admin"))],
)


def _record_to_dto(record: SessionRecord) -> JobDTO:
    return JobDTO(
        session_id=record.session_id,
        account_id=record.account_id,
        started_at=record.started_at,
        ended_at=record.ended_at,
        proxy_country=record.proxy_country,
        user_agent=record.user_agent,
        target_streams_attempted=record.target_streams_attempted,
        camouflage_streams_attempted=record.camouflage_streams_attempted,
        streams_counted=record.streams_counted,
        skips=record.skips,
        likes_given=record.likes_given,
        saves_given=record.saves_given,
        follows_given=record.follows_given,
        error_class=record.error_class,
        completed_normally=record.completed_normally,
    )


@router.get(
    "/jobs",
    response_model=PaginatedResponse[JobDTO],
    summary="Lista de jobs (sesiones) recientes",
    description=(
        "Devuelve las sesiones ejecutadas en orden DESC por started_at. "
        "Filtros opcionales: account_id. En v2 se anadiran filtros por "
        "rango de fechas y status."
    ),
)
async def list_jobs(
    session: Annotated[AsyncSession, Depends(get_session)],
    account_id: Annotated[
        str | None,
        Query(description="Filtra por id de cuenta listening."),
    ] = None,
    cursor: Annotated[str | None, Query(description="Cursor opaco")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
) -> PaginatedResponse[JobDTO]:
    stmt = select(SessionRecordModel).order_by(SessionRecordModel.started_at.desc())
    if account_id is not None:
        stmt = stmt.where(SessionRecordModel.account_id == account_id)
    result = await session.execute(stmt)
    records = [to_domain_session_record(m) for m in result.scalars().all()]
    return paginate(records, limit=limit, cursor=cursor, map_item=_record_to_dto)


@router.get(
    "/jobs/{job_id}",
    response_model=JobDTO,
    summary="Detalle de un job",
    description="Resuelve un job/sesion por id. 404 si no existe.",
)
async def get_job(
    job_id: Annotated[str, Path(description="session_id del job")],
    sessions_repo: Annotated[
        ISessionRecordRepository,
        Depends(get_session_record_repository),
    ],
) -> JobDTO:
    record = await sessions_repo.get(job_id)
    if record is None:
        raise NotFoundError("job", job_id)
    return _record_to_dto(record)


@router.get(
    "/sessions/{session_id}",
    response_model=JobDTO,
    summary="Detalle de una sesion (alias semantico)",
    description=(
        "Endpoint alias del detalle de job; expuesto para clarificar el "
        "nombre cuando el cliente esta razonando sobre 'sesiones' del bot."
    ),
)
async def get_session_record(
    session_id: Annotated[str, Path(description="UUID4 del SessionRecord")],
    sessions_repo: Annotated[
        ISessionRecordRepository,
        Depends(get_session_record_repository),
    ],
) -> JobDTO:
    record = await sessions_repo.get(session_id)
    if record is None:
        raise NotFoundError("session", session_id)
    return _record_to_dto(record)
