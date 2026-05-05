"""Puerto opcional para snapshots de TrackHealthScore.

La implementacion principal vive en ClickHouse (lectura sobre
``stream_events`` / ``behavior_events``). Este puerto permite cachear
y consultar scores ya calculados desde otras capas (planner ML,
catalog pipeline, distribution) sin acoplarlas al SQL concreto.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from streaming_bot.domain.routing.track_health import TrackHealthScore
from streaming_bot.domain.value_objects import Country


@runtime_checkable
class ITrackHealthRepository(Protocol):
    """Acceso a snapshots de salud de track persistidos en CH."""

    async def get(
        self,
        track_id: str,
        *,
        as_of: datetime,
    ) -> TrackHealthScore | None:
        """Devuelve el snapshot mas reciente <= ``as_of`` o ``None``.

        ``track_id`` es el spotify_uri completo (``spotify:track:XXX``).
        """
        ...

    async def upsert(self, track_id: str, score: TrackHealthScore) -> None:
        """Persiste un snapshot. Idempotente por (track_id, computed_at)."""
        ...

    async def streams_24h_by_country(
        self,
        track_id: str,
        *,
        as_of: datetime,
    ) -> dict[Country, int]:
        """Conteo de streams ``counted`` en 24h agrupado por proxy_country."""
        ...
