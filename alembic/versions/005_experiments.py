"""experiments framework: experiments + variants + variant_assignments

Revision ID: 005_experiments
Revises: 002_artist_label_multi
Create Date: 2026-05-04 17:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005_experiments"
down_revision: str | None = "002_artist_label_multi"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Crea las tres tablas del framework de A/B testing."""
    op.create_table(
        "experiments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("hypothesis", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("control_variant_id", sa.String(length=36), nullable=False),
        sa.Column(
            "traffic_allocation",
            sa.Float(),
            nullable=False,
            server_default="1.0",
        ),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metrics_targets", sa.JSON(), nullable=False),
        sa.Column("winner_variant_id", sa.String(length=36), nullable=True),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.String(length=2048), nullable=False, server_default=""),
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
    op.create_index("ix_experiments_status", "experiments", ["status"])

    op.create_table(
        "experiment_variants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("allocation_weight", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            name="fk_experiment_variants_experiment_id_experiments",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_experiment_variants_experiment_position",
        "experiment_variants",
        ["experiment_id", "position"],
    )

    op.create_table(
        "variant_assignments",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("variant_id", sa.String(length=36), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_variant_assignments_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            name="fk_variant_assignments_experiment_id_experiments",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "account_id",
            "experiment_id",
            name="uq_variant_assignments_account_experiment",
        ),
    )
    op.create_index(
        "ix_variant_assignments_account_id",
        "variant_assignments",
        ["account_id"],
    )


def downgrade() -> None:
    """Revierte la creacion (orden inverso de FKs)."""
    op.drop_index("ix_variant_assignments_account_id", table_name="variant_assignments")
    op.drop_table("variant_assignments")
    op.drop_index(
        "ix_experiment_variants_experiment_position",
        table_name="experiment_variants",
    )
    op.drop_table("experiment_variants")
    op.drop_index("ix_experiments_status", table_name="experiments")
    op.drop_table("experiments")
