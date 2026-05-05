"""distribution multi-distributor tables

Revision ID: 004_distribution
Revises: 002_artist_label_multi
Create Date: 2026-05-04 17:00:00.000000

NOTA OPS: si en el merge de ramas ya existe 003_*, reapuntar `down_revision`
a esa migracion antes de aplicar (alembic upgrade detectara la cadena
desordenada y no aplicara). Por ahora queda colgada de 002 para no bloquear
el desarrollo del Multi-Distributor Dispatcher v1.

Crea las tablas:
- `releases`            : registro de cada release enviado a un distribuidor.
- `release_submissions` : submission_id devuelto por cada distribuidor + status.
- `artist_aliases`      : mapping (track_id, distributor) -> alias_name.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004_distribution"
down_revision: str | None = "002_artist_label_multi"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Crea tablas para el dispatcher multi-distribuidor."""
    op.create_table(
        "releases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("track_id", sa.String(length=36), nullable=False),
        sa.Column("distributor", sa.String(length=32), nullable=False),
        sa.Column("artist_name", sa.String(length=255), nullable=False),
        sa.Column("label_name", sa.String(length=255), nullable=False),
        sa.Column("release_date", sa.Date(), nullable=False),
        sa.Column("isrc", sa.String(length=32), nullable=True),
        sa.Column("upc", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("tracks_metadata", sa.JSON(), nullable=False, server_default="[]"),
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
    op.create_index("ix_releases_distributor_status", "releases", ["distributor", "status"])
    op.create_index("ix_releases_track_id", "releases", ["track_id"])

    op.create_table(
        "release_submissions",
        sa.Column("submission_id", sa.String(length=255), primary_key=True),
        sa.Column(
            "release_id",
            sa.String(length=36),
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("distributor", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="submitted"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=True),
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
    op.create_index(
        "ix_release_submissions_release_id",
        "release_submissions",
        ["release_id"],
    )
    op.create_index(
        "ix_release_submissions_distributor_status",
        "release_submissions",
        ["distributor", "status"],
    )

    op.create_table(
        "artist_aliases",
        sa.Column("track_id", sa.String(length=36), primary_key=True),
        sa.Column("distributor", sa.String(length=32), primary_key=True),
        sa.Column("alias_name", sa.String(length=255), nullable=False),
        sa.Column("label_name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_artist_aliases_distributor",
        "artist_aliases",
        ["distributor"],
    )
    op.create_index(
        "ix_artist_aliases_alias_name",
        "artist_aliases",
        ["alias_name"],
    )


def downgrade() -> None:
    """Reverse migration: drop dispatcher tables."""
    op.drop_index("ix_artist_aliases_alias_name", table_name="artist_aliases")
    op.drop_index("ix_artist_aliases_distributor", table_name="artist_aliases")
    op.drop_table("artist_aliases")

    op.drop_index(
        "ix_release_submissions_distributor_status",
        table_name="release_submissions",
    )
    op.drop_index("ix_release_submissions_release_id", table_name="release_submissions")
    op.drop_table("release_submissions")

    op.drop_index("ix_releases_track_id", table_name="releases")
    op.drop_index("ix_releases_distributor_status", table_name="releases")
    op.drop_table("releases")
