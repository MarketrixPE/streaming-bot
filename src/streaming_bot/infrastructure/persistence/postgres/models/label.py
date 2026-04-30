"""Modelo ORM de Label (sello/cuenta distribuidor)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from streaming_bot.infrastructure.persistence.postgres.models.base import (
    Base,
    TimestampMixin,
)


class LabelModel(Base, TimestampMixin):
    """Sello/cuenta donde se distribuye y monitorea la musica.

    Un Label puede agrupar multiples Artists. La salud del label condiciona
    si se sigue boosteando: warning -> reduce throughput; suspended -> stop.
    """

    __tablename__ = "labels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    distributor: Mapped[str] = mapped_column(String(32), nullable=False)
    distributor_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    health: Mapped[str] = mapped_column(String(32), nullable=False, default="healthy")
    last_health_check: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (Index("ix_labels_distributor_health", "distributor", "health"),)
