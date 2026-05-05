"""Implementación del puerto ``IClickhouseFeatureRepo`` con httpx.

ClickHouse expone una HTTP interface en :8123 que devuelve JSON cuando
añadimos ``FORMAT JSON``. Esto evita pulling el driver nativo
(clickhouse-driver) y mantiene el adapter ligero.

Estrategia de queries:
- Usamos las vistas materializadas pre-agregadas (``stream_events_hourly``,
  ``account_health_snapshots``) cuando es posible para no scan completo.
- Las queries se ejecutan en paralelo via ``asyncio.gather``.
- Los rates (save/skip/queue) salen de ``account_health_snapshots`` ya
  pre-calculados; los rollups manuales se hacen sobre ``stream_events``
  filtrando por particion mensual.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from streaming_bot.application.ml.feature_extractor import (
    IClickhouseFeatureRepo,
    _ClickhouseRollup,
)

if TYPE_CHECKING:
    import httpx


class ClickhouseFeatureRepo(IClickhouseFeatureRepo):
    """Adapter HTTP de ClickHouse para extraer features pre-agregadas."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str = "http://localhost:8123",
        database: str = "events",
        timeout_seconds: float = 5.0,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._db = database
        self._timeout = timeout_seconds

    async def fetch_rollup(
        self,
        *,
        account_id: str,
        as_of: datetime,
    ) -> _ClickhouseRollup:
        """Lanza queries en paralelo y agrega el resultado."""
        from_24h = as_of - timedelta(hours=24)
        from_7d = as_of - timedelta(days=7)
        from_30d = as_of - timedelta(days=30)
        results = await asyncio.gather(
            self._query_streams_window(
                account_id=account_id,
                from_dt=from_24h,
                to_dt=as_of,
            ),
            self._query_streams_window(
                account_id=account_id,
                from_dt=from_7d,
                to_dt=as_of,
            ),
            self._query_health_snapshot(account_id=account_id, as_of=as_of),
            self._query_quarantine_count(
                account_id=account_id,
                from_dt=from_30d,
                to_dt=as_of,
            ),
            return_exceptions=False,
        )
        rollup_24h_dict, rollup_7d_dict, snapshot_dict, quarantines_count = results

        return _ClickhouseRollup(
            streams_24h=rollup_24h_dict.get("total", 0.0),
            streams_7d=rollup_7d_dict.get("total", 0.0),
            failed_streams_24h=rollup_24h_dict.get("failed", 0.0),
            partial_streams_24h=rollup_24h_dict.get("partial", 0.0),
            ip_diversity_24h=rollup_24h_dict.get("distinct_ips", 0.0),
            distinct_dsps_24h=rollup_24h_dict.get("distinct_dsps", 0.0),
            distinct_artists_24h=rollup_24h_dict.get("distinct_artists", 0.0),
            distinct_tracks_24h=rollup_24h_dict.get("distinct_tracks", 0.0),
            country_changes_24h=rollup_24h_dict.get("distinct_countries", 0.0),
            night_streams_ratio_24h=rollup_24h_dict.get("night_ratio", 0.0),
            user_agent_changes_7d=rollup_7d_dict.get("distinct_user_agents", 0.0),
            captcha_encounters_24h=rollup_24h_dict.get("captcha_count", 0.0),
            rapid_skip_ratio_24h=rollup_24h_dict.get("rapid_skip_ratio", 0.0),
            save_rate_24h=snapshot_dict.get("save_rate", 0.0),
            skip_rate_24h=snapshot_dict.get("skip_rate", 0.0),
            queue_rate_24h=snapshot_dict.get("queue_rate", 0.0),
            geo_consistency_score=snapshot_dict.get("geo_consistency_score", 1.0),
            hour_of_day_consistency=snapshot_dict.get("hour_consistency", 1.0),
            fingerprint_age_days=snapshot_dict.get("fingerprint_age_days", 0.0),
            previous_quarantine_count_30d=quarantines_count,
        )

    async def _query_streams_window(
        self,
        *,
        account_id: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> dict[str, float]:
        """Conteos básicos sobre ``stream_events`` en ventana.

        Usamos ``WHERE`` por ``account_id`` y la columna PRIMARY KEY
        ``occurred_at`` para que ClickHouse use el índice y la partición.
        """
        sql = f"""
        SELECT
            count() AS total,
            countIf(outcome = 'failed') AS failed,
            countIf(outcome = 'partial') AS partial,
            uniqExact(proxy_ip_hash) AS distinct_ips,
            uniqExact(dsp) AS distinct_dsps,
            uniqExact(artist_uri) AS distinct_artists,
            uniqExact(track_uri) AS distinct_tracks,
            uniqExact(proxy_country) AS distinct_countries,
            countIf(toHour(occurred_at) IN (0,1,2,3,4,5)) /
                greatest(count(), 1) AS night_ratio,
            uniqExact(fingerprint_id) AS distinct_user_agents,
            countIf(error_message LIKE '%captcha%') AS captcha_count,
            countIf(outcome = 'skipped' AND duration_seconds < 5) /
                greatest(count(), 1) AS rapid_skip_ratio
        FROM {self._db}.stream_events
        WHERE account_id = {{aid:String}}
          AND occurred_at >= {{ts_from:DateTime64(3)}}
          AND occurred_at <  {{ts_to:DateTime64(3)}}
        FORMAT JSON
        """
        params = {
            "aid": account_id,
            "ts_from": from_dt.isoformat(),
            "ts_to": to_dt.isoformat(),
        }
        return await self._fetch_first_row(sql=sql, params=params)

    async def _query_health_snapshot(
        self,
        *,
        account_id: str,
        as_of: datetime,
    ) -> dict[str, float]:
        """Último snapshot de salud disponible (cubre ratios)."""
        sql = f"""
        SELECT
            save_rate,
            skip_rate,
            queue_rate,
            anomaly_score,
            -- Estos campos se calculan offline en otra MV; defaults seguros si faltan.
            1.0 AS geo_consistency_score,
            1.0 AS hour_consistency,
            0.0 AS fingerprint_age_days
        FROM {self._db}.account_health_snapshots
        WHERE account_id = {{aid:String}}
          AND snapshot_at <= {{ts:DateTime64(3)}}
        ORDER BY snapshot_at DESC
        LIMIT 1
        FORMAT JSON
        """
        params = {"aid": account_id, "ts": as_of.isoformat()}
        return await self._fetch_first_row(sql=sql, params=params)

    async def _query_quarantine_count(
        self,
        *,
        account_id: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> float:
        """Número de transiciones a 'quarantined' en los últimos 30 días."""
        sql = f"""
        SELECT countIf(state = 'quarantined') AS qcount
        FROM {self._db}.account_health_snapshots
        WHERE account_id = {{aid:String}}
          AND snapshot_at >= {{ts_from:DateTime64(3)}}
          AND snapshot_at <  {{ts_to:DateTime64(3)}}
        FORMAT JSON
        """
        params = {
            "aid": account_id,
            "ts_from": from_dt.isoformat(),
            "ts_to": to_dt.isoformat(),
        }
        row = await self._fetch_first_row(sql=sql, params=params)
        return float(row.get("qcount", 0.0))

    async def _fetch_first_row(
        self,
        *,
        sql: str,
        params: dict[str, str],
    ) -> dict[str, float]:
        """Ejecuta SQL y devuelve la primera fila como dict[str, float].

        Usa ``param_*`` query string que ClickHouse mapea a placeholders
        ``{name:Type}`` dentro del SQL — evita SQL injection sin
        introducir un driver completo.
        """
        query_params: dict[str, str] = {f"param_{k}": v for k, v in params.items()}
        query_params["query"] = sql
        response = await self._client.post(
            self._base_url + "/",
            params=query_params,
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        rows = payload.get("data", [])
        if not rows:
            return {}
        first = rows[0]
        return {k: float(v) if v is not None else 0.0 for k, v in first.items()}
