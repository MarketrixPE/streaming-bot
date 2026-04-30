"""initial schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-04-27 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Crea todas las tablas iniciales del esquema de persistencia.

    Las columnas JSON se declaran con `sa.JSON` (genérico portátil); en
    Postgres se promueven a JSONB en runtime mediante `with_variant` desde
    los modelos declarativos.
    """
    op.create_table(
        "songs",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("spotify_uri", sa.String(length=64), nullable=False),
        sa.Column("isrc", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("artist_name", sa.String(length=255), nullable=False),
        sa.Column("artist_uri", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("distributor", sa.String(length=32), nullable=True),
        sa.Column("album_name", sa.String(length=512), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "baseline_streams_per_day",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("target_streams_per_day", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("safe_ceiling_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_streams_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("top_country_distribution", sa.JSON(), nullable=False),
        sa.Column(
            "spike_oct2025_flag",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint("spotify_uri", name="uq_songs_spotify_uri"),
    )
    op.create_index("ix_songs_isrc", "songs", ["isrc"])
    op.create_index("ix_songs_artist_uri", "songs", ["artist_uri"])
    op.create_index("ix_songs_role_active", "songs", ["role", "is_active"])
    op.create_index(
        "ix_songs_role_spike_baseline",
        "songs",
        ["role", "spike_oct2025_flag", "baseline_streams_per_day"],
    )

    op.create_table(
        "personas",
        sa.Column("account_id", sa.String(length=36), primary_key=True),
        sa.Column("engagement_level", sa.String(length=32), nullable=False),
        sa.Column("preferred_genres", sa.JSON(), nullable=False),
        sa.Column("preferred_session_hour_start", sa.Integer(), nullable=False),
        sa.Column("preferred_session_hour_end", sa.Integer(), nullable=False),
        sa.Column("device", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("ui_language", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("behaviors", sa.JSON(), nullable=False),
        sa.Column("typing", sa.JSON(), nullable=False),
        sa.Column("mouse", sa.JSON(), nullable=False),
        sa.Column("session_pattern", sa.JSON(), nullable=False),
        sa.Column("created_at_iso", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("last_session_at_iso", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("password_encrypted", sa.String(length=1024), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("persona_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint("username", name="uq_accounts_username"),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["personas.account_id"],
            name="fk_accounts_persona_id_personas",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_accounts_state_last_used_at", "accounts", ["state", "last_used_at"])
    op.create_index("ix_accounts_country_state", "accounts", ["country", "state"])

    op.create_table(
        "persona_memory_snapshots",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("liked_songs", sa.JSON(), nullable=False),
        sa.Column("saved_songs", sa.JSON(), nullable=False),
        sa.Column("followed_artists", sa.JSON(), nullable=False),
        sa.Column("followed_playlists", sa.JSON(), nullable=False),
        sa.Column("own_playlists", sa.JSON(), nullable=False),
        sa.Column("recent_searches", sa.JSON(), nullable=False),
        sa.Column("recent_artists_visited", sa.JSON(), nullable=False),
        sa.Column("total_stream_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_streams", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["personas.account_id"],
            name="fk_persona_memory_snapshots_account_id_personas",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_persona_memory_account_snapshot_at",
        "persona_memory_snapshots",
        ["account_id", "snapshot_at"],
    )

    op.create_table(
        "playlists",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("spotify_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("owner_account_id", sa.String(length=36), nullable=True),
        sa.Column("territory", sa.String(length=2), nullable=True),
        sa.Column("genre", sa.String(length=64), nullable=True),
        sa.Column("description", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("cover_image_path", sa.String(length=512), nullable=True),
        sa.Column("follower_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint("spotify_id", name="uq_playlists_spotify_id"),
        sa.ForeignKeyConstraint(
            ["owner_account_id"],
            ["accounts.id"],
            name="fk_playlists_owner_account_id_accounts",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_playlists_kind_territory", "playlists", ["kind", "territory"])
    op.create_index("ix_playlists_owner_kind", "playlists", ["owner_account_id", "kind"])

    op.create_table(
        "playlist_tracks",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("playlist_id", sa.String(length=36), nullable=False),
        sa.Column("track_uri", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_target", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artist_uri", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=512), nullable=False, server_default=""),
        sa.UniqueConstraint(
            "playlist_id",
            "track_uri",
            name="uq_playlist_tracks_playlist_uri",
        ),
        sa.ForeignKeyConstraint(
            ["playlist_id"],
            ["playlists.id"],
            name="fk_playlist_tracks_playlist_id_playlists",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_playlist_tracks_track_uri_is_target",
        "playlist_tracks",
        ["track_uri", "is_target"],
    )

    op.create_table(
        "modems",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("imei", sa.String(length=32), nullable=False),
        sa.Column("iccid", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("serial_port", sa.String(length=64), nullable=False),
        sa.Column("operator", sa.String(length=64), nullable=False),
        sa.Column("sim_country", sa.String(length=2), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="ready"),
        sa.Column("current_public_ip", sa.String(length=45), nullable=True),
        sa.Column("last_rotation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accounts_used_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("streams_served_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("flagged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("max_accounts_per_day", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("max_streams_per_day", sa.Integer(), nullable=False, server_default="250"),
        sa.Column("rotation_cooldown_seconds", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("use_cooldown_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint("imei", name="uq_modems_imei"),
        sa.UniqueConstraint("iccid", name="uq_modems_iccid"),
    )
    op.create_index("ix_modems_country_state", "modems", ["sim_country", "state"])
    op.create_index("ix_modems_state_last_used", "modems", ["state", "last_used_at"])

    op.create_table(
        "stream_history",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("song_id", sa.String(length=26), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("target_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("listen_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("proxy_used", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_stream_history_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["song_id"],
            ["songs.id"],
            name="fk_stream_history_song_id_songs",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_stream_history_session_id", "stream_history", ["session_id"])
    op.create_index(
        "ix_stream_history_account_song_started",
        "stream_history",
        ["account_id", "song_id", "started_at"],
    )
    op.create_index(
        "ix_stream_history_song_started",
        "stream_history",
        ["song_id", "started_at"],
    )
    op.create_index(
        "ix_stream_history_outcome_started",
        "stream_history",
        ["outcome", "started_at"],
    )

    op.create_table(
        "session_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("persona_id", sa.String(length=36), nullable=True),
        sa.Column("modem_id", sa.String(length=36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_streams", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_streams", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("behaviors", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_session_records_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["personas.account_id"],
            name="fk_session_records_persona_id_personas",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["modem_id"],
            ["modems.id"],
            name="fk_session_records_modem_id_modems",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_session_records_account_started",
        "session_records",
        ["account_id", "started_at"],
    )


def downgrade() -> None:
    """Tear down completo (orden inverso de FKs)."""
    op.drop_table("session_records")
    op.drop_table("stream_history")
    op.drop_table("modems")
    op.drop_table("playlist_tracks")
    op.drop_table("playlists")
    op.drop_table("persona_memory_snapshots")
    op.drop_table("accounts")
    op.drop_table("personas")
    op.drop_table("songs")
