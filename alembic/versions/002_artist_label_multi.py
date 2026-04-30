"""artist + label tables and multi-artist song fields

Revision ID: 002_artist_label_multi
Revises: 001_initial_schema
Create Date: 2026-04-27 08:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002_artist_label_multi"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add labels + artists tables and extend songs with multi-artist FKs."""
    op.create_table(
        "labels",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("distributor", sa.String(length=32), nullable=False),
        sa.Column("distributor_account_id", sa.String(length=255), nullable=True),
        sa.Column("owner_email", sa.String(length=255), nullable=True),
        sa.Column(
            "health",
            sa.String(length=32),
            nullable=False,
            server_default="healthy",
        ),
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_labels_name", "labels", ["name"])
    op.create_index(
        "ix_labels_distributor_health", "labels", ["distributor", "health"]
    )

    op.create_table(
        "artists",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("spotify_uri", sa.String(length=64), nullable=True, unique=True),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("primary_country", sa.String(length=8), nullable=True),
        sa.Column(
            "primary_genres", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "label_id",
            sa.String(length=36),
            sa.ForeignKey("labels.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "has_spike_history",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_artists_name", "artists", ["name"])
    op.create_index("ix_artists_status", "artists", ["status"])
    op.create_index(
        "ix_artists_label_id_status", "artists", ["label_id", "status"]
    )

    with op.batch_alter_table("songs") as batch:
        batch.add_column(
            sa.Column(
                "primary_artist_id",
                sa.String(length=36),
                sa.ForeignKey("artists.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "featured_artist_ids",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )
        batch.add_column(
            sa.Column(
                "label_id",
                sa.String(length=36),
                sa.ForeignKey("labels.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "tier",
                sa.String(length=16),
                nullable=False,
                server_default="mid",
            )
        )
        batch.add_column(
            sa.Column(
                "flag_notes", sa.Text(), nullable=False, server_default=""
            )
        )

    op.create_index("ix_songs_primary_artist_id", "songs", ["primary_artist_id"])
    op.create_index("ix_songs_label_id", "songs", ["label_id"])
    op.create_index("ix_songs_tier_active", "songs", ["tier", "is_active"])
    op.create_index(
        "ix_songs_primary_artist_tier",
        "songs",
        ["primary_artist_id", "tier"],
    )


def downgrade() -> None:
    """Reverse migration: drop multi-artist columns then artists+labels."""
    op.drop_index("ix_songs_primary_artist_tier", table_name="songs")
    op.drop_index("ix_songs_tier_active", table_name="songs")
    op.drop_index("ix_songs_label_id", table_name="songs")
    op.drop_index("ix_songs_primary_artist_id", table_name="songs")
    with op.batch_alter_table("songs") as batch:
        batch.drop_column("flag_notes")
        batch.drop_column("tier")
        batch.drop_column("label_id")
        batch.drop_column("featured_artist_ids")
        batch.drop_column("primary_artist_id")

    op.drop_index("ix_artists_label_id_status", table_name="artists")
    op.drop_index("ix_artists_status", table_name="artists")
    op.drop_index("ix_artists_name", table_name="artists")
    op.drop_table("artists")

    op.drop_index("ix_labels_distributor_health", table_name="labels")
    op.drop_index("ix_labels_name", table_name="labels")
    op.drop_table("labels")
