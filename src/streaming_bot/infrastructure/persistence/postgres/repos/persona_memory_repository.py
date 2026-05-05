"""Implementacion Postgres del puerto `IPersonaMemoryRepository`.

Reglas de la implementacion:
- `apply_delta` hace bulk-insert con `add_all` + un solo `flush`. Mas eficiente
  que N inserts independientes y conserva atomicidad dentro de la transaccion
  externa (la abre el use case via `AsyncSession`).
- `get_state` reconstruye el agregado en memoria a partir del log completo.
  Para personas con miles de eventos esta operacion es O(N); si en el futuro
  necesitamos low-latency reads se puede materializar un snapshot en
  `persona_memory_snapshots` (ya existente) y este repo solo escribira el log.
- `list_recent_actions` aprovecha el indice `ix_persona_memory_events_persona_ts`.

No emitimos commit aqui: respetamos el patron Unit-of-Work del use case.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.ports.persona_memory_repo import (
    PersonaMemoryAggregate,
    PersonaMemoryEvent,
    PersonaMemoryEventType,
)
from streaming_bot.infrastructure.persistence.postgres.models.persona_memory import (
    PersonaMemoryEventModel,
)


class PostgresPersonaMemoryRepository:
    """Implementacion del puerto event-sourced sobre Postgres/SQLite."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def apply_delta(
        self,
        *,
        persona_id: str,
        account_id: str,
        events: Sequence[PersonaMemoryEvent],
    ) -> None:
        """Persiste el lote completo via `add_all` + flush.

        Ignora silenciosamente lotes vacios para no malgastar un roundtrip.
        """
        if not events:
            return
        models = [
            PersonaMemoryEventModel(
                persona_id=persona_id,
                account_id=account_id,
                event_type=event.event_type.value,
                target_uri=event.target_uri,
                timestamp=event.timestamp,
                event_metadata=dict(event.metadata),
            )
            for event in events
        ]
        self._session.add_all(models)
        await self._session.flush()

    async def get_state(self, persona_id: str) -> PersonaMemoryAggregate:
        """Reconstruye el agregado a partir del log completo de la persona.

        Sets se preservan en orden de aparicion (`dict.fromkeys`) para que el
        timeline visual siga siendo determinista; los duplicados se eliminan.
        """
        stmt = (
            select(PersonaMemoryEventModel)
            .where(PersonaMemoryEventModel.persona_id == persona_id)
            .order_by(PersonaMemoryEventModel.timestamp.asc())
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return self._fold(persona_id=persona_id, rows=rows)

    async def list_recent_actions(
        self,
        persona_id: str,
        *,
        limit: int = 50,
    ) -> list[PersonaMemoryEvent]:
        """Devuelve los `limit` eventos mas recientes en orden DESC."""
        if limit <= 0:
            return []
        stmt = (
            select(PersonaMemoryEventModel)
            .where(PersonaMemoryEventModel.persona_id == persona_id)
            .order_by(PersonaMemoryEventModel.timestamp.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars().all()]

    @staticmethod
    def _fold(
        *,
        persona_id: str,
        rows: Sequence[PersonaMemoryEventModel],
    ) -> PersonaMemoryAggregate:
        """Reduce una lista de eventos a un agregado inmutable."""
        liked: dict[str, None] = {}
        saved: dict[str, None] = {}
        playlist: dict[str, None] = {}
        queued: list[str] = []
        followed: dict[str, None] = {}
        visited: list[str] = []
        searches: list[str] = []
        streamed_minutes = 0
        streams_counted = 0
        last_ts = None

        for row in rows:
            last_ts = row.timestamp
            try:
                kind = PersonaMemoryEventType(row.event_type)
            except ValueError:
                # Tipos desconocidos no rompen la reconstruccion: los ignoramos
                # con un contador implicito en `total_events` (count(rows)).
                continue
            uri = row.target_uri
            metadata: dict[str, Any] = row.event_metadata or {}

            if kind is PersonaMemoryEventType.LIKE and uri:
                liked.setdefault(uri, None)
            elif kind is PersonaMemoryEventType.SAVE and uri:
                saved.setdefault(uri, None)
            elif kind is PersonaMemoryEventType.ADD_TO_PLAYLIST and uri:
                playlist.setdefault(uri, None)
            elif kind is PersonaMemoryEventType.ADD_TO_QUEUE and uri:
                queued.append(uri)
            elif kind is PersonaMemoryEventType.FOLLOW_ARTIST and uri:
                followed.setdefault(uri, None)
            elif kind is PersonaMemoryEventType.VISIT_ARTIST and uri:
                visited.append(uri)
            elif kind is PersonaMemoryEventType.SEARCH:
                query = str(metadata.get("query") or uri or "")
                if query:
                    searches.append(query)
            elif kind is PersonaMemoryEventType.STREAM:
                minutes_raw = metadata.get("minutes", 0)
                streamed_minutes += int(minutes_raw) if isinstance(minutes_raw, int) else 0
                if bool(metadata.get("counted", False)):
                    streams_counted += 1

        return PersonaMemoryAggregate(
            persona_id=persona_id,
            liked_uris=tuple(liked.keys()),
            saved_uris=tuple(saved.keys()),
            added_to_playlist_uris=tuple(playlist.keys()),
            queued_uris=tuple(queued),
            followed_artists=tuple(followed.keys()),
            visited_artists=tuple(visited),
            searches=tuple(searches),
            streamed_minutes=streamed_minutes,
            streams_counted=streams_counted,
            last_event_at=last_ts,
            total_events=len(rows),
        )


def _to_domain(row: PersonaMemoryEventModel) -> PersonaMemoryEvent:
    """Mapea una fila ORM al evento de dominio."""
    return PersonaMemoryEvent(
        persona_id=row.persona_id,
        account_id=row.account_id,
        event_type=PersonaMemoryEventType(row.event_type),
        timestamp=row.timestamp,
        target_uri=row.target_uri,
        metadata=dict(row.event_metadata or {}),
    )
