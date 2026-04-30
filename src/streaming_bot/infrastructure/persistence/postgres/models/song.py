"""Modelo ORM del catálogo de canciones (target/camuflaje/discovery)."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from streaming_bot.infrastructure.persistence.postgres.models.base import (
    Base,
    TimestampMixin,
    ulid_pk,
)


class SongModel(Base, TimestampMixin):
    """Canción del catálogo con métricas operativas para el scheduler.

    Multi-artist: `primary_artist_id` es FK a Artist; `featured_artist_ids`
    es lista (JSON) de FKs adicionales para feats. `label_id` apunta al
    sello/cuenta distribuidor.
    """

    __tablename__ = "songs"

    id: Mapped[str] = ulid_pk()
    spotify_uri: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    isrc: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    artist_name: Mapped[str] = mapped_column(String(255), nullable=False)
    artist_uri: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    distributor: Mapped[str | None] = mapped_column(String(32), nullable=True)
    album_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    primary_artist_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("artists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    featured_artist_ids: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
    )
    label_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("labels.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    baseline_streams_per_day: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    target_streams_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safe_ceiling_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_streams_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tier: Mapped[str] = mapped_column(String(16), nullable=False, default="mid")

    top_country_distribution: Mapped[dict[str, float]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )

    spike_oct2025_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    flag_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        Index("ix_songs_role_active", "role", "is_active"),
        Index(
            "ix_songs_role_spike_baseline",
            "role",
            "spike_oct2025_flag",
            "baseline_streams_per_day",
        ),
        Index("ix_songs_tier_active", "tier", "is_active"),
        Index("ix_songs_primary_artist_tier", "primary_artist_id", "tier"),
    )
