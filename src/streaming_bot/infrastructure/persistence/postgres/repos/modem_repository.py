"""Repositorio Postgres de modems del pool 4G/5G."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.modem import Modem
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.models.modem import ModemModel
from streaming_bot.infrastructure.persistence.postgres.repos.mappers import (
    apply_modem_to_model,
    from_domain_modem,
    to_domain_modem,
)


class PostgresModemRepository:
    """Implementación de `IModemRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, modem_id: str) -> Modem | None:
        """Lookup por PK; útil al reanudar tras reinicio del orquestador."""
        model = await self._session.get(ModemModel, modem_id)
        return to_domain_modem(model) if model is not None else None

    async def add(self, modem: Modem) -> None:
        """INSERT. PK reutiliza el UUID4 del dominio."""
        self._session.add(from_domain_modem(modem))
        await self._session.flush()

    async def update(self, modem: Modem) -> None:
        """UPDATE de estado/contadores; falla si el modem no fue dado de alta."""
        model = await self._session.get(ModemModel, modem.id)
        if model is None:
            raise DomainError(f"modem no encontrado para update: {modem.id}")
        apply_modem_to_model(modem, model)
        await self._session.flush()

    async def list_all(self) -> list[Modem]:
        """Listado completo (admin/diagnostics)."""
        result = await self._session.execute(select(ModemModel))
        return [to_domain_modem(m) for m in result.scalars().all()]

    async def list_by_country(self, country: Country) -> list[Modem]:
        """Modems con SIM del país solicitado.

        Usa el índice `(sim_country, state)` y ordena por uso reciente para
        que el asignador devuelva el LRU primero.
        """
        stmt = (
            select(ModemModel)
            .where(ModemModel.sim_country == country.value)
            .order_by(ModemModel.last_used_at.asc().nulls_first())
        )
        result = await self._session.execute(stmt)
        return [to_domain_modem(m) for m in result.scalars().all()]
