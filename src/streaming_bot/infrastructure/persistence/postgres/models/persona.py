"""Modelos ORM de Persona: traits inmutables + snapshots de memoria.

Por qué dos tablas:
- `personas` guarda traits estables (engagement, device, behaviors). Una fila
  por cuenta (PK = account_id, FK 1:1).
- `persona_memory_snapshots` es append-only: cada `update_memory` inserta una
  nueva fila con la memoria evolutiva (likes/follows/searches). Mantener
  histórico permite análisis longitudinal del crecimiento orgánico.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from streaming_bot.infrastructure.persistence.postgres.models.base import (
    Base,
    TimestampMixin,
    ulid_pk,
)


class PersonaModel(Base, TimestampMixin):
    """Traits estables de la persona asociada a una cuenta."""

    __tablename__ = "personas"

    # 1:1 con accounts (no se duplica account_id entre personas).
    account_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )
    engagement_level: Mapped[str] = mapped_column(String(32), nullable=False)
    # Lista de géneros: JSON array para portabilidad sqlite/postgres.
    preferred_genres: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    preferred_session_hour_start: Mapped[int] = mapped_column(Integer, nullable=False)
    preferred_session_hour_end: Mapped[int] = mapped_column(Integer, nullable=False)
    device: Mapped[str] = mapped_column(String(32), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    ui_language: Mapped[str] = mapped_column(String(16), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)

    # Sub-perfiles serializados como JSON heterogéneo (int + float coexisten):
    # caben en una sola consulta y se editan en bloque vía dataclasses.asdict.
    behaviors: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    typing: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    mouse: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    session_pattern: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )

    created_at_iso: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    last_session_at_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PersonaMemorySnapshotModel(Base):
    """Snapshot de memoria evolutiva de una persona en un instante dado."""

    __tablename__ = "persona_memory_snapshots"

    id: Mapped[str] = ulid_pk()
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("personas.account_id", ondelete="CASCADE"),
        nullable=False,
    )
    # Sets se serializan como listas JSON: orden no importa, lectura íntegra.
    liked_songs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    saved_songs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    followed_artists: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    followed_playlists: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    own_playlists: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    recent_searches: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    recent_artists_visited: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    total_stream_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_streams: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        # Recuperar el snapshot más reciente de una cuenta es la consulta caliente.
        Index("ix_persona_memory_account_snapshot_at", "account_id", "snapshot_at"),
    )
