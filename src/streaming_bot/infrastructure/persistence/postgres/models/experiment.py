"""Modelos ORM del framework de A/B testing.

Tres tablas:
- ``experiments``: agregado raiz con metadata (status, ventana, targets).
- ``experiment_variants``: variantes asociadas (FK con ``ON DELETE CASCADE``).
- ``variant_assignments``: snapshot sticky por (cuenta, experimento) con
  unique compuesto que evita duplicados.

Decisiones:
- ``params`` y ``metrics_targets`` se serializan como JSON con variant a
  JSONB en Postgres (mismo patron que ``persona.behaviors``).
- ``id`` de ``experiments``/``variants`` es ``String(36)`` (UUID4 generado
  por el dominio); ``variant_assignments.id`` es ULID interno (append-only).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from streaming_bot.infrastructure.persistence.postgres.models.base import (
    Base,
    TimestampMixin,
    ulid_pk,
)


class ExperimentModel(Base, TimestampMixin):
    """Tabla ``experiments``: agregado raiz."""

    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hypothesis: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    control_variant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    traffic_allocation: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metrics_targets: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    winner_variant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(String(2048), nullable=False, default="")

    __table_args__ = (
        # Filtro caliente: el VariantResolver pide RUNNING en cada lookup.
        Index("ix_experiments_status", "status"),
    )


class ExperimentVariantModel(Base):
    """Tabla ``experiment_variants``: variantes de un experimento."""

    __tablename__ = "experiment_variants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    allocation_weight: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        # El orden estable de iteracion del aggregator depende de (exp, position).
        Index("ix_experiment_variants_experiment_position", "experiment_id", "position"),
    )


class VariantAssignmentModel(Base):
    """Tabla ``variant_assignments``: asignacion sticky por (cuenta, experimento)."""

    __tablename__ = "variant_assignments"

    id: Mapped[str] = ulid_pk()
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    experiment_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    variant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "experiment_id",
            name="uq_variant_assignments_account_experiment",
        ),
        # Listado por cuenta (debugging/dashboards).
        Index("ix_variant_assignments_account_id", "account_id"),
    )
