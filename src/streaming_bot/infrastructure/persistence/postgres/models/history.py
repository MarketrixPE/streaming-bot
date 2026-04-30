"""Modelos ORM para auditoría: streams individuales y sesiones completas."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from streaming_bot.infrastructure.persistence.postgres.models.base import Base, ulid_pk


class StreamHistoryModel(Base):
    """Cada intento de stream queda registrado para enforce de cooldown 72h.

    El índice compuesto `(account_id, song_id, started_at)` soporta la query
    caliente `count_for_account_today` y la búsqueda de cooldown 72h.
    """

    __tablename__ = "stream_history"

    id: Mapped[str] = ulid_pk()
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    song_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("songs.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    target_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    listen_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    proxy_used: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_stream_history_account_song_started", "account_id", "song_id", "started_at"),
        Index("ix_stream_history_song_started", "song_id", "started_at"),
        Index("ix_stream_history_outcome_started", "outcome", "started_at"),
    )


class SessionRecordModel(Base):
    """Sesión completa de una cuenta: agrupa N streams + behaviors."""

    __tablename__ = "session_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    persona_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("personas.account_id", ondelete="SET NULL"),
        nullable=True,
    )
    modem_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("modems.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    total_streams: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_streams: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Lista de eventos de comportamiento serializada (event_id, type, ts, ...).
    # Mantener inline evita JOIN para el caso 99%: leer la sesión de un tirón.
    behaviors: Mapped[list[dict[str, str | int]]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
    )

    __table_args__ = (Index("ix_session_records_account_started", "account_id", "started_at"),)
