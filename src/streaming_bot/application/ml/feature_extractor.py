"""Extractor de ``AccountFeatureVector``.

Cruza dos fuentes:
- ``IClickhouseFeatureRepo``: rollups y conteos en ClickHouse (cheap).
- ``ISessionRecordRepository`` / ``IStreamHistoryRepository``: histórico
  granular en Postgres (sesiones, behaviors, errores).

Este componente vive en application porque encapsula la *lógica de
combinación* de fuentes; las queries crudas se delegan a infraestructura.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from streaming_bot.domain.ml.feature_vector import FEATURE_NAMES, AccountFeatureVector

if TYPE_CHECKING:
    from collections.abc import Callable

    from streaming_bot.domain.history import SessionRecord
    from streaming_bot.domain.ports.history_repo import (
        ISessionRecordRepository,
    )


@dataclass(frozen=True, slots=True)
class _ClickhouseRollup:
    """Conteos pre-agregados por ClickHouse para una cuenta dada."""

    streams_24h: float = 0.0
    streams_7d: float = 0.0
    save_rate_24h: float = 0.0
    skip_rate_24h: float = 0.0
    queue_rate_24h: float = 0.0
    ip_diversity_24h: float = 0.0
    distinct_dsps_24h: float = 0.0
    captcha_encounters_24h: float = 0.0
    failed_streams_24h: float = 0.0
    partial_streams_24h: float = 0.0
    distinct_artists_24h: float = 0.0
    distinct_tracks_24h: float = 0.0
    night_streams_ratio_24h: float = 0.0
    rapid_skip_ratio_24h: float = 0.0
    country_changes_24h: float = 0.0
    user_agent_changes_7d: float = 0.0
    previous_quarantine_count_30d: float = 0.0
    fingerprint_age_days: float = 0.0
    geo_consistency_score: float = 1.0
    hour_of_day_consistency: float = 1.0


@runtime_checkable
class IClickhouseFeatureRepo(Protocol):
    """Puerto para queries ClickHouse pre-agregadas.

    La implementación concreta usa httpx para hablar con :8123 y consume
    ``stream_events_hourly`` y ``account_health_snapshots``.
    """

    async def fetch_rollup(
        self,
        *,
        account_id: str,
        as_of: datetime,
    ) -> _ClickhouseRollup: ...


class FeatureExtractor:
    """Construye ``AccountFeatureVector`` a partir de las fuentes."""

    def __init__(
        self,
        *,
        clickhouse_repo: IClickhouseFeatureRepo,
        session_repo: ISessionRecordRepository,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._ch = clickhouse_repo
        self._sessions = session_repo
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    async def extract(self, account_id: str) -> AccountFeatureVector:
        as_of = self._now_factory()
        rollup = await self._ch.fetch_rollup(account_id=account_id, as_of=as_of)
        sessions = await self._sessions.list_for_account(account_id, limit=200)
        session_metrics = self._derive_session_metrics(
            sessions=sessions,
            as_of=as_of,
        )
        merged = {
            "streams_24h": rollup.streams_24h,
            "streams_7d": rollup.streams_7d,
            "save_rate_24h": _clip01(rollup.save_rate_24h),
            "skip_rate_24h": _clip01(rollup.skip_rate_24h),
            "queue_rate_24h": _clip01(rollup.queue_rate_24h),
            "ip_diversity_24h": rollup.ip_diversity_24h,
            "fingerprint_age_days": rollup.fingerprint_age_days,
            "distinct_dsps_24h": rollup.distinct_dsps_24h,
            "hour_of_day_consistency": _clip01(rollup.hour_of_day_consistency),
            "geo_consistency_score": _clip01(rollup.geo_consistency_score),
            "captcha_encounters_24h": rollup.captcha_encounters_24h,
            "failed_streams_24h": rollup.failed_streams_24h,
            "partial_streams_24h": rollup.partial_streams_24h,
            "completion_rate_24h": _completion_rate(rollup),
            "sessions_24h": session_metrics["sessions_24h"],
            "avg_session_duration_minutes": session_metrics["avg_session_duration_minutes"],
            "distinct_artists_24h": rollup.distinct_artists_24h,
            "distinct_tracks_24h": rollup.distinct_tracks_24h,
            "repeat_track_ratio_24h": _repeat_track_ratio(rollup),
            "night_streams_ratio_24h": _clip01(rollup.night_streams_ratio_24h),
            "rapid_skip_ratio_24h": _clip01(rollup.rapid_skip_ratio_24h),
            "country_changes_24h": rollup.country_changes_24h,
            "user_agent_changes_7d": rollup.user_agent_changes_7d,
            "previous_quarantine_count_30d": rollup.previous_quarantine_count_30d,
        }
        # Aseguramos que todas las features esperadas están presentes (defensa
        # ante futuros cambios). Si alguna falta, se rellena con 0.
        for name in FEATURE_NAMES:
            merged.setdefault(name, 0.0)
        return AccountFeatureVector.from_dict(account_id=account_id, values=merged)

    @staticmethod
    def _derive_session_metrics(
        *,
        sessions: list[SessionRecord],
        as_of: datetime,
    ) -> dict[str, float]:
        """Calcula métricas de sesión a partir del histórico Postgres.

        Solo cuenta sesiones de las últimas 24h para mantener consistencia
        con el resto de las features ``*_24h``.
        """
        cutoff = as_of - timedelta(hours=24)
        recent = [s for s in sessions if s.started_at >= cutoff]
        if not recent:
            return {"sessions_24h": 0.0, "avg_session_duration_minutes": 0.0}
        total_minutes = 0.0
        for session in recent:
            if session.ended_at is None:
                continue
            total_minutes += (session.ended_at - session.started_at).total_seconds() / 60.0
        avg = total_minutes / len(recent) if recent else 0.0
        return {
            "sessions_24h": float(len(recent)),
            "avg_session_duration_minutes": float(avg),
        }


def _clip01(value: float) -> float:
    """Garantiza que el valor cae en [0,1]; saturando si excede."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _completion_rate(rollup: _ClickhouseRollup) -> float:
    """Ratio de streams ``counted`` sobre total atribuible.

    Total = counted (streams_24h - failed - partial) + partial + failed.
    Si no hay actividad, devolvemos 0.0 (no hay señal).
    """
    total = rollup.streams_24h
    if total <= 0.0:
        return 0.0
    counted = max(total - rollup.failed_streams_24h - rollup.partial_streams_24h, 0.0)
    return _clip01(counted / total)


def _repeat_track_ratio(rollup: _ClickhouseRollup) -> float:
    """Ratio de repetición = 1 - (tracks_distintos / total_streams).

    Una cuenta sospechosa de bot tiende a repetir mucho la misma canción
    target; ratios altos disparan el modelo.
    """
    if rollup.streams_24h <= 0.0:
        return 0.0
    distinct = min(rollup.distinct_tracks_24h, rollup.streams_24h)
    return _clip01(1.0 - distinct / rollup.streams_24h)


__all__ = [
    "FeatureExtractor",
    "IClickhouseFeatureRepo",
    "_ClickhouseRollup",
    "_completion_rate",
    "_repeat_track_ratio",
]
