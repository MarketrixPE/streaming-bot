"""Repositorio Postgres de ``VariantAssignment`` (sticky por cuenta+experimento)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.experiments.assignment import VariantAssignment
from streaming_bot.infrastructure.persistence.postgres.models.experiment import (
    VariantAssignmentModel,
)


class PostgresVariantAssignmentRepository:
    """Implementacion de ``IVariantAssignmentRepository`` con unique compuesto."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self,
        account_id: str,
        experiment_id: str,
    ) -> VariantAssignment | None:
        """Lookup por (account_id, experiment_id). Devuelve ``None`` si no existe."""
        stmt = select(VariantAssignmentModel).where(
            VariantAssignmentModel.account_id == account_id,
            VariantAssignmentModel.experiment_id == experiment_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _to_domain(model) if model is not None else None

    async def add(self, assignment: VariantAssignment) -> None:
        """INSERT estricto. La unique constraint protege la stickyness."""
        self._session.add(_to_model(assignment))
        await self._session.flush()

    async def list_for_account(self, account_id: str) -> list[VariantAssignment]:
        """Listado de asignaciones de una cuenta (uso administrativo/debug)."""
        stmt = select(VariantAssignmentModel).where(
            VariantAssignmentModel.account_id == account_id,
        )
        result = await self._session.execute(stmt)
        return [_to_domain(m) for m in result.scalars().all()]


def _to_model(assignment: VariantAssignment) -> VariantAssignmentModel:
    return VariantAssignmentModel(
        account_id=assignment.account_id,
        experiment_id=assignment.experiment_id,
        variant_id=assignment.variant_id,
        assigned_at=assignment.assigned_at,
    )


def _to_domain(model: VariantAssignmentModel) -> VariantAssignment:
    return VariantAssignment(
        account_id=model.account_id,
        experiment_id=model.experiment_id,
        variant_id=model.variant_id,
        assigned_at=model.assigned_at,
    )
