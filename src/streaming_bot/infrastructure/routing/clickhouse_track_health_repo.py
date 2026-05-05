"""Implementacion de ``ITrackHealthRepository`` sobre ClickHouse HTTP.

ClickHouse expone una HTTP interface en :8123 que devuelve JSON cuando
se le pasa ``FORMAT JSON``. Aprovechamos los rollups de la base
``events`` (``stream_events`` raw + ``stream_events_hourly`` MV) sin
introducir un driver nativo: solo ``httpx`` (ya en deps).

Notas de diseno:
- ``stream_events_hourly`` agrega por (dsp, tier, country, hour) sin
  granularidad por ``track_uri``. Por eso las queries por track
  consultan ``stream_events`` filtrando por particion mensual via
  ``occurred_at``.
- ``upsert`` se deja como no-op hasta que exista una tabla dedicada
  ``events.track_health_snapshots``. La firma del puerto se mantiene
  para no acoplar callers a la ausencia de cache.
- La saturacion se computa con la ``RoutingPolicy`` inyectada para
  poder traducir cada pais a su tier y aplicar ``max_safe``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from streaming_bot.application.routing.policy import RoutingPolicy
from streaming_bot.domain.routing.track_health import TrackHealthScore
from streaming_bot.domain.value_objects import Country

if TYPE_CHECKING:
    import httpx


class ClickhouseTrackHealthRepository:
    """Adapter de lectura sobre la base ``events`` de ClickHouse."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        policy: RoutingPolicy | None = None,
        base_url: str = "http://localhost:8123",
        database: str = "events",
        timeout_seconds: float = 5.0,
    ) -> None:
        self._client = client
        self._policy = policy if policy is not None else RoutingPolicy()
        self._base_url = base_url.rstrip("/")
        self._db = database
        self._timeout = timeout_seconds

    async def get(
        self,
        track_id: str,
        *,
        as_of: datetime,
    ) -> TrackHealthScore | None:
        """Reconstruye un snapshot a partir de los rollups disponibles.

        Devuelve ``None`` si no hay datos suficientes en 30d (track sin
        eventos). ``age_days`` queda en 0: la responsabilidad de
        rellenarlo recae en el ``TrackHealthScorer`` (necesita
        ``release_date`` que solo el catalogo conoce).
        """
        from_30d = as_of - timedelta(days=30)
        from_24h = as_of - timedelta(hours=24)

        plays_skip, saves, streams_by_country = await asyncio.gather(
            self._query_plays_and_skip(
                track_uri=track_id,
                from_dt=from_30d,
                to_dt=as_of,
            ),
            self._query_saves(
                track_uri=track_id,
                from_dt=from_30d,
                to_dt=as_of,
            ),
            self._query_streams_by_country(
                track_uri=track_id,
                from_dt=from_24h,
                to_dt=as_of,
            ),
        )
        attempts = int(plays_skip.get("attempts", 0))
        if attempts == 0 and not streams_by_country and saves == 0:
            return None

        plays_30d = int(plays_skip.get("plays", 0))
        skipped = int(plays_skip.get("skipped", 0))
        skip_rate = skipped / attempts if attempts > 0 else 0.0
        save_rate = min(saves / plays_30d, 1.0) if plays_30d > 0 else 0.0
        saturation = self._compute_saturation(streams_by_country)
        return TrackHealthScore(
            age_days=0,
            plays_30d=plays_30d,
            save_rate=save_rate,
            skip_rate=skip_rate,
            saturation_score=saturation,
            computed_at=as_of,
        )

    async def upsert(self, track_id: str, score: TrackHealthScore) -> None:
        """No-op hasta tener tabla dedicada ``events.track_health_snapshots``.

        Se conserva la firma para cumplir el puerto sin acoplar callers
        a la ausencia de la tabla. Cuando se cree la MV/tabla se
        reemplaza con un INSERT idempotente por (track_id, computed_at).
        """
        # Marcamos los args como usados para satisfacer ruff (ARG002).
        del track_id, score

    async def streams_24h_by_country(
        self,
        track_id: str,
        *,
        as_of: datetime,
    ) -> dict[Country, int]:
        from_24h = as_of - timedelta(hours=24)
        return await self._query_streams_by_country(
            track_uri=track_id,
            from_dt=from_24h,
            to_dt=as_of,
        )

    def _compute_saturation(
        self,
        streams_by_country: dict[Country, int],
    ) -> float:
        """Aplica la policy para traducir streams_24h a saturation."""
        if not streams_by_country:
            return 0.0
        max_sat = 0.0
        for country, streams in streams_by_country.items():
            tier = self._policy.tier_for_country(country)
            if tier is None:
                continue
            max_safe = self._policy.max_safe_streams_24h(tier)
            ratio = streams / max_safe
            max_sat = max(max_sat, ratio)
        return max_sat

    async def _query_plays_and_skip(
        self,
        *,
        track_uri: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> dict[str, float]:
        """Counts COUNTED/SKIPPED/total para skip_rate y plays_30d."""
        # ``self._db`` viene del constructor (config controlada), nunca de
        # input usuario. Los demas placeholders se bindean via param_*.
        sql = f"""
        SELECT
            countIf(outcome = 'counted')                       AS plays,
            countIf(outcome = 'skipped')                       AS skipped,
            countIf(outcome IN ('counted','partial','skipped','failed','blocked'))
                AS attempts
        FROM {self._db}.stream_events
        WHERE track_uri = {{track:String}}
          AND occurred_at >= {{ts_from:DateTime64(3)}}
          AND occurred_at <  {{ts_to:DateTime64(3)}}
        FORMAT JSON
        """  # noqa: S608
        params = {
            "track": track_uri,
            "ts_from": from_dt.isoformat(),
            "ts_to": to_dt.isoformat(),
        }
        return await self._fetch_first_row(sql=sql, params=params)

    async def _query_saves(
        self,
        *,
        track_uri: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> int:
        """Saves desde behavior_events (save_to_library + add_to_playlist)."""
        sql = f"""
        SELECT count() AS saves
        FROM {self._db}.behavior_events
        WHERE target_uri = {{track:String}}
          AND behavior IN ('save_to_library','add_to_playlist')
          AND occurred_at >= {{ts_from:DateTime64(3)}}
          AND occurred_at <  {{ts_to:DateTime64(3)}}
        FORMAT JSON
        """  # noqa: S608
        params = {
            "track": track_uri,
            "ts_from": from_dt.isoformat(),
            "ts_to": to_dt.isoformat(),
        }
        row = await self._fetch_first_row(sql=sql, params=params)
        return int(row.get("saves", 0))

    async def _query_streams_by_country(
        self,
        *,
        track_uri: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> dict[Country, int]:
        """Conteo de streams ``counted`` por proxy_country en la ventana."""
        sql = f"""
        SELECT proxy_country AS country, count() AS streams
        FROM {self._db}.stream_events
        WHERE track_uri = {{track:String}}
          AND outcome = 'counted'
          AND occurred_at >= {{ts_from:DateTime64(3)}}
          AND occurred_at <  {{ts_to:DateTime64(3)}}
        GROUP BY proxy_country
        FORMAT JSON
        """  # noqa: S608
        params = {
            "track": track_uri,
            "ts_from": from_dt.isoformat(),
            "ts_to": to_dt.isoformat(),
        }
        rows = await self._fetch_rows(sql=sql, params=params)
        result: dict[Country, int] = {}
        for row in rows:
            code = str(row.get("country", ""))
            try:
                country = Country(code)
            except ValueError:
                continue
            result[country] = int(row.get("streams", 0))
        return result

    async def _fetch_first_row(
        self,
        *,
        sql: str,
        params: dict[str, str],
    ) -> dict[str, float]:
        rows = await self._fetch_rows(sql=sql, params=params)
        if not rows:
            return {}
        first = rows[0]
        return {k: float(v) if v is not None else 0.0 for k, v in first.items()}

    async def _fetch_rows(
        self,
        *,
        sql: str,
        params: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Ejecuta SQL con ``param_*`` query string para evitar inyeccion."""
        query_params: dict[str, str] = {f"param_{k}": v for k, v in params.items()}
        query_params["query"] = sql
        response = await self._client.post(
            self._base_url + "/",
            params=query_params,
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return cast(list[dict[str, Any]], payload.get("data", []))
