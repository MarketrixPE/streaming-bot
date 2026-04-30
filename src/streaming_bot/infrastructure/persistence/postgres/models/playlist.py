"""Modelos ORM de playlists y sus tracks ordenados."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from streaming_bot.infrastructure.persistence.postgres.models.base import (
    Base,
    TimestampMixin,
    ulid_pk,
)


class PlaylistModel(Base, TimestampMixin):
    """Playlist persistida. Los tracks se cargan eagerly por `selectin`."""

    __tablename__ = "playlists"

    # PK reutiliza UUID4 del dominio (`Playlist.new()` los genera con uuid4).
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    spotify_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_account_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    territory: Mapped[str | None] = mapped_column(String(2), nullable=True)
    genre: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    cover_image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    follower_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Eager-loading con selectin: una playlist nunca se usa sin sus tracks.
    tracks: Mapped[list[PlaylistTrackModel]] = relationship(
        back_populates="playlist",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="PlaylistTrackModel.position",
    )

    __table_args__ = (
        Index("ix_playlists_kind_territory", "kind", "territory"),
        Index("ix_playlists_owner_kind", "owner_account_id", "kind"),
    )


class PlaylistTrackModel(Base):
    """Track dentro de una playlist con su rol estratégico (target/camuflaje)."""

    __tablename__ = "playlist_tracks"

    id: Mapped[str] = ulid_pk()
    playlist_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("playlists.id", ondelete="CASCADE"),
        nullable=False,
    )
    track_uri: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_target: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    artist_uri: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    playlist: Mapped[PlaylistModel] = relationship(back_populates="tracks")

    __table_args__ = (
        # Una misma URI no puede aparecer dos veces en la misma playlist
        # (refleja `Playlist.add_track` que lanza ValueError en duplicado).
        UniqueConstraint("playlist_id", "track_uri", name="uq_playlist_tracks_playlist_uri"),
        # Consulta caliente: ¿qué playlists targetean esta canción?
        Index("ix_playlist_tracks_track_uri_is_target", "track_uri", "is_target"),
    )
