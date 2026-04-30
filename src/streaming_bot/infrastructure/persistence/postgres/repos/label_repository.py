"""Repositorio Postgres de labels (sellos / cuentas distribuidor)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.label import DistributorType, Label, LabelHealth
from streaming_bot.infrastructure.persistence.postgres.models.label import LabelModel
from streaming_bot.infrastructure.persistence.postgres.repos.mappers import (
    apply_label_to_model,
    from_domain_label,
    to_domain_label,
)


class PostgresLabelRepository:
    """Implementación de `ILabelRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, label: Label) -> None:
        existing = await self._session.get(LabelModel, label.id)
        if existing is None:
            self._session.add(from_domain_label(label))
        else:
            apply_label_to_model(label, existing)
        await self._session.flush()

    async def get(self, label_id: str) -> Label | None:
        model = await self._session.get(LabelModel, label_id)
        return to_domain_label(model) if model is not None else None

    async def get_by_name(self, name: str) -> Label | None:
        stmt = select(LabelModel).where(LabelModel.name == name)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return to_domain_label(model) if model is not None else None

    async def list_by_distributor(self, distributor: DistributorType) -> list[Label]:
        stmt = select(LabelModel).where(LabelModel.distributor == distributor.value)
        result = await self._session.execute(stmt)
        return [to_domain_label(m) for m in result.scalars().all()]

    async def list_by_health(self, health: LabelHealth) -> list[Label]:
        stmt = select(LabelModel).where(LabelModel.health == health.value)
        result = await self._session.execute(stmt)
        return [to_domain_label(m) for m in result.scalars().all()]

    async def list_all(self) -> list[Label]:
        stmt = select(LabelModel).order_by(LabelModel.name)
        result = await self._session.execute(stmt)
        return [to_domain_label(m) for m in result.scalars().all()]

    async def delete(self, label_id: str) -> None:
        model = await self._session.get(LabelModel, label_id)
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()
