"""Modelo ORM de Artist (multi-artist support)."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from streaming_bot.infrastructure.persistence.postgres.models.base import (
    Base,
    TimestampMixin,
)


class ArtistModel(Base, TimestampMixin):
    """Artista cuyas canciones se boostean.

    Multi-artist support: cada cancion del catalogo tiene FK a un Artist.
    Cada artista puede tener pool aislado de cuentas/modems para no contaminar
    fingerprints entre proyectos.
    """

    __tablename__ = "artists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    spotify_uri: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    aliases: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
    )
    primary_country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    primary_genres: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
    )
    label_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("labels.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    has_spike_history: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        Index("ix_artists_status", "status"),
        Index("ix_artists_label_id_status", "label_id", "status"),
    )
