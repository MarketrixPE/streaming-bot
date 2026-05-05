"""Router /v1 metricas: KPIs agregados y series simples para el dashboard.

- ``/v1/metrics/summary``: KPIs agregados (totales por tabla).
- ``/v1/metrics/streams_by_dsp``: conteo de streams por DSP en ventana
  configurable.
- ``/v1/metrics/anomalies/active``: cuentas en risk_level HIGH/CRITICAL.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.song import SongRole
from streaming_bot.infrastructure.persistence.postgres.models.account import AccountModel
from streaming_bot.infrastructure.persistence.postgres.models.artist import ArtistModel
from streaming_bot.infrastructure.persistence.postgres.models.history import (
    SessionRecordModel,
    StreamHistoryModel,
)
from streaming_bot.infrastructure.persistence.postgres.models.label import LabelModel
from streaming_bot.infrastructure.persistence.postgres.models.song import SongModel
from streaming_bot.presentation.api.dependencies import (
    get_container,
    get_session,
    require_role,
)
from streaming_bot.presentation.api.schemas import (
    AnomalyAlertDTO,
    KpiSummaryDTO,
    StreamsByDspDTO,
)

router = APIRouter(
    prefix="/v1/metrics",
    tags=["metrics"],
    dependencies=[Depends(require_role("viewer", "operator", "admin"))],
)


def _today_range_utc() -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    start = datetime.combine(now.date(), time.min, UTC)
    end = datetime.combine(now.date(), time.max, UTC)
    return start, end


@router.get(
    "/summary",
    response_model=KpiSummaryDTO,
    summary="KPIs agregados de operacion",
    description=(
        "Conteos rapidos para el overview del dashboard: cuentas, "
        "artistas, labels, songs y conteos del dia (sesiones + streams)."
    ),
)
async def metrics_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KpiSummaryDTO:
    start_today, end_today = _today_range_utc()
    accounts_total = await session.scalar(select(func.count()).select_from(AccountModel))
    accounts_active = await session.scalar(
        select(func.count())
        .select_from(AccountModel)
        .where(AccountModel.state == "active"),
    )
    songs_total = await session.scalar(select(func.count()).select_from(SongModel))
    songs_active_targets = await session.scalar(
        select(func.count())
        .select_from(SongModel)
        .where(
            SongModel.role == SongRole.TARGET.value,
            SongModel.is_active.is_(True),
        ),
    )
    artists_total = await session.scalar(select(func.count()).select_from(ArtistModel))
    labels_total = await session.scalar(select(func.count()).select_from(LabelModel))
    sessions_today = await session.scalar(
        select(func.count())
        .select_from(SessionRecordModel)
        .where(SessionRecordModel.started_at >= start_today),
    )
    streams_counted_today = await session.scalar(
        select(func.count())
        .select_from(StreamHistoryModel)
        .where(
            StreamHistoryModel.started_at >= start_today,
            StreamHistoryModel.started_at < end_today,
            StreamHistoryModel.outcome == "counted",
        ),
    )
    return KpiSummaryDTO(
        accounts_total=int(accounts_total or 0),
        accounts_active=int(accounts_active or 0),
        songs_total=int(songs_total or 0),
        songs_active_targets=int(songs_active_targets or 0),
        artists_total=int(artists_total or 0),
        labels_total=int(labels_total or 0),
        sessions_today=int(sessions_today or 0),
        streams_counted_today=int(streams_counted_today or 0),
    )


@router.get(
    "/streams_by_dsp",
    response_model=StreamsByDspDTO,
    summary="Conteo de streams por DSP",
    description=(
        "Devuelve los streams contados (>=30s) agrupados por DSP destino. "
        "v1 expone solo el bucket spotify; futuros DSP se sumaran cuando "
        "el modelo de history exponga la columna correspondiente."
    ),
)
async def streams_by_dsp(
    session: Annotated[AsyncSession, Depends(get_session)],
    window: Annotated[
        Literal["today", "last_24h", "last_7d"],
        Query(description="Ventana temporal del agregado."),
    ] = "today",
) -> StreamsByDspDTO:
    now = datetime.now(UTC)
    if window == "today":
        start = datetime.combine(now.date(), time.min, UTC)
    elif window == "last_24h":
        start = now - timedelta(hours=24)
    else:
        start = now - timedelta(days=7)
    counted = await session.scalar(
        select(func.count())
        .select_from(StreamHistoryModel)
        .where(
            StreamHistoryModel.started_at >= start,
            StreamHistoryModel.outcome == "counted",
        ),
    )
    return StreamsByDspDTO(by_dsp={"spotify": int(counted or 0)}, window=window)


def _resolve_predictor(container: Any) -> Any | None:
    return getattr(container, "anomaly_predictor", None)


@router.get(
    "/anomalies/active",
    response_model=list[AnomalyAlertDTO],
    summary="Anomalias activas",
    description=(
        "Cuentas en risk_level HIGH/CRITICAL segun el predictor ML. "
        "Si el predictor no esta cableado en el container devuelve "
        "lista vacia (modo dev)."
    ),
)
async def active_anomalies(
    session: Annotated[AsyncSession, Depends(get_session)],
    container: Annotated[Any, Depends(get_container)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AnomalyAlertDTO]:
    predictor = _resolve_predictor(container)
    if predictor is None:
        return []
    stmt = (
        select(AccountModel.id, AccountModel.username)
        .where(AccountModel.state == "active")
        .order_by(AccountModel.last_used_at.desc().nulls_last())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows: list[tuple[str, str]] = [(row[0], row[1]) for row in result.all()]
    if not rows:
        return []
    account_ids = [row[0] for row in rows]
    scores = await predictor.predict_batch(account_ids)
    by_id = {row[0]: row[1] for row in rows}
    alerts: list[AnomalyAlertDTO] = []
    for score in scores:
        risk = score.risk_level.value.lower()
        if risk in {"high", "critical"}:
            alerts.append(
                AnomalyAlertDTO(
                    account_id=score.account_id,
                    username=by_id.get(score.account_id),
                    score=score.score,
                    risk_level=risk,
                    reason=None,
                    detected_at=score.computed_at,
                )
            )
    return alerts
