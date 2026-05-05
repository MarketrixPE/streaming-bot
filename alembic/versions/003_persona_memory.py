"""persona memory event-sourced log

Revision ID: 003_persona_memory
Revises: 004_distribution
Create Date: 2026-05-04 17:30:00.000000

NOTA OPS: esta migracion se anade despues de 004_distribution para mantener
una unica cabeza en Alembic. La numeracion del archivo (003) refleja la
plantilla del feature, no la posicion topologica en la cadena. Si en el
futuro se reordena el merge de ramas, basta con reapuntar `down_revision`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003_persona_memory"
down_revision: str | None = "004_distribution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Crea la tabla event-sourced de memoria de persona."""
    op.create_table(
        "persona_memory_events",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("persona_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("target_uri", sa.String(length=255), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["personas.account_id"],
            name="fk_persona_memory_events_persona_id_personas",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_persona_memory_events_persona_ts",
        "persona_memory_events",
        ["persona_id", "timestamp"],
    )
    op.create_index(
        "ix_persona_memory_events_account_ts",
        "persona_memory_events",
        ["account_id", "timestamp"],
    )
    op.create_index(
        "ix_persona_memory_events_type_ts",
        "persona_memory_events",
        ["event_type", "timestamp"],
    )


def downgrade() -> None:
    """Tear down de la tabla event-sourced (drop indexes implicit)."""
    op.drop_index(
        "ix_persona_memory_events_type_ts",
        table_name="persona_memory_events",
    )
    op.drop_index(
        "ix_persona_memory_events_account_ts",
        table_name="persona_memory_events",
    )
    op.drop_index(
        "ix_persona_memory_events_persona_ts",
        table_name="persona_memory_events",
    )
    op.drop_table("persona_memory_events")
