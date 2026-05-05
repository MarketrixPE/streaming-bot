"""Puerto de repositorio para la memoria evolutiva (event-sourced) de la persona.

A diferencia de `IPersonaRepository.update_memory` (snapshot agregado), aqui
modelamos cada accion humana como un evento atomico (`PersonaMemoryEvent`).
El repositorio persiste el log y permite reconstruir el agregado actual o
listar el timeline reciente para auditoria.

Beneficios de event-log:
- Auditoria fina: que paso, cuando y con que metadata por persona.
- Reproducibilidad: podemos reconstruir el estado a un instante T.
- Compatible con la `PersonaMemoryDelta` actual: se conserva la API in-memory
  y se le anade un sumidero persistente opcional.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class PersonaMemoryEventType(str, Enum):
    """Tipos atomicos de evento que la engine puede registrar.

    Mantener este enum acotado a las acciones que afectan la memoria evolutiva
    (no se mezclan eventos de telemetria del browser ni de ciclo de vida).
    """

    LIKE = "like"
    SAVE = "save"
    ADD_TO_PLAYLIST = "playlist_add"
    ADD_TO_QUEUE = "queue_add"
    FOLLOW_ARTIST = "follow_artist"
    VISIT_ARTIST = "visit_artist"
    SEARCH = "search"
    STREAM = "stream"


@dataclass(frozen=True, slots=True)
class PersonaMemoryEvent:
    """Evento atomico de memoria de una persona.

    `target_uri` es opcional: en `STREAM` o `SEARCH` el objetivo va en metadata.
    `metadata` queda como JSON libre para anotar contexto (ej: minutos de
    stream, query original, fuente de descubrimiento).
    """

    persona_id: str
    account_id: str
    event_type: PersonaMemoryEventType
    timestamp: datetime
    target_uri: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PersonaMemoryAggregate:
    """Estado agregado reconstruido a partir del log de eventos.

    Tipos `tuple` para inmutabilidad: el agregado es una vista de solo lectura.
    Las consultas de UI o RBAC pueden tomar decisiones sin tocar el log crudo.
    """

    persona_id: str
    liked_uris: tuple[str, ...] = ()
    saved_uris: tuple[str, ...] = ()
    added_to_playlist_uris: tuple[str, ...] = ()
    queued_uris: tuple[str, ...] = ()
    followed_artists: tuple[str, ...] = ()
    visited_artists: tuple[str, ...] = ()
    searches: tuple[str, ...] = ()
    streamed_minutes: int = 0
    streams_counted: int = 0
    last_event_at: datetime | None = None
    total_events: int = 0


@runtime_checkable
class IPersonaMemoryRepository(Protocol):
    """Repositorio event-sourced de memoria de personas.

    Implementaciones concretas viven en infrastructure (Postgres por defecto).
    El dominio depende solo de esta abstraccion.
    """

    async def apply_delta(
        self,
        *,
        persona_id: str,
        account_id: str,
        events: Sequence[PersonaMemoryEvent],
    ) -> None:
        """Persiste un lote de eventos generados en una sesion.

        Implementaciones SQL deberian usar bulk-insert (transaccion unica)
        para no inflar el numero de roundtrips por sesion.
        """
        ...

    async def get_state(self, persona_id: str) -> PersonaMemoryAggregate:
        """Reconstruye el agregado actual leyendo el log completo.

        Si la persona no tiene eventos, devuelve un agregado vacio con el
        `persona_id` correcto (no `None`) para evitar checks redundantes en
        callers.
        """
        ...

    async def list_recent_actions(
        self,
        persona_id: str,
        *,
        limit: int = 50,
    ) -> list[PersonaMemoryEvent]:
        """Devuelve los `limit` eventos mas recientes (orden DESC por timestamp)."""
        ...
