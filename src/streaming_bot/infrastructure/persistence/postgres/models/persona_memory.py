"""Modelo ORM del log event-sourced de memoria de persona.

Append-only: cada accion humana relevante (like, save, follow, search, etc.)
es una fila. Indexamos por `(persona_id, timestamp)` porque las queries
caliente son:
- listar las ultimas N acciones de una persona (timeline RBAC)
- reconstruir agregado leyendo todo el log de la persona

Diferencia con `persona_memory_snapshots` (creada en 001_initial_schema):
- Snapshots: estado consolidado por sesion, util para "leer la memoria total".
- Events: log de cambios, util para auditoria fina y replay.

Ambos coexisten: el snapshot se mantiene para retrocompatibilidad del
`IPersonaRepository.update_memory()`, mientras que el log alimenta el nuevo
`IPersonaMemoryRepository` event-sourced.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from streaming_bot.infrastructure.persistence.postgres.models.base import Base, ulid_pk


class PersonaMemoryEventModel(Base):
    """Cada fila representa una accion atomica registrada por el behavior engine.

    Notas de diseno:
    - `persona_id` y `account_id` se separan: hoy son 1:1, pero si en el
      futuro una cuenta cambia de persona el log mantiene la integridad
      retroactiva.
    - `event_metadata` (no `metadata`, que es atributo reservado de
      `DeclarativeBase`) se serializa como JSONB en Postgres y JSON portable
      en SQLite (tests).
    - Indice compuesto cubre la query principal `ORDER BY timestamp DESC
      LIMIT N` para una persona.
    """

    __tablename__ = "persona_memory_events"

    id: Mapped[str] = ulid_pk()
    persona_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("personas.account_id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_uri: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "event_metadata",
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )

    __table_args__ = (
        Index("ix_persona_memory_events_persona_ts", "persona_id", "timestamp"),
        Index("ix_persona_memory_events_account_ts", "account_id", "timestamp"),
        Index("ix_persona_memory_events_type_ts", "event_type", "timestamp"),
    )
