"""Repositorio Postgres de cuentas."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.entities import Account
from streaming_bot.domain.exceptions import DomainError
from streaming_bot.infrastructure.persistence.postgres.models.account import AccountModel
from streaming_bot.infrastructure.persistence.postgres.repos.mappers import (
    apply_account_to_model,
    from_domain_account,
    to_domain_account,
)


class PostgresAccountRepository:
    """Implementación de `IAccountRepository` sobre Postgres/SQLite asyncio."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def all(self) -> list[Account]:
        """Devuelve todas las cuentas (uso administrativo, no scheduler)."""
        result = await self._session.execute(select(AccountModel))
        return [to_domain_account(m) for m in result.scalars().all()]

    async def get(self, account_id: str) -> Account:
        """Obtiene por PK; lanza DomainError si no existe (contrato del puerto)."""
        model = await self._session.get(AccountModel, account_id)
        if model is None:
            raise DomainError(f"cuenta no encontrada: {account_id}")
        return to_domain_account(model)

    async def get_by_username(self, username: str) -> Account | None:
        """Login flow: lookup por username (uniq)."""
        stmt = select(AccountModel).where(AccountModel.username == username)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return to_domain_account(model) if model is not None else None

    async def add(self, account: Account) -> None:
        """INSERT estricto: el caller debe garantizar id único."""
        self._session.add(from_domain_account(account))
        await self._session.flush()

    async def update(self, account: Account) -> None:
        """UPDATE estricto: si la cuenta no existe, falla el contrato."""
        model = await self._session.get(AccountModel, account.id)
        if model is None:
            raise DomainError(
                f"cuenta no encontrada para update: {account.id}",
            )
        apply_account_to_model(account, model)
        await self._session.flush()

    async def list_active(self) -> list[Account]:
        """Cuentas operativas; ordenadas por `last_used_at` (LRU first).

        Usa el índice compuesto `(state, last_used_at)`. NULL primero porque
        cuentas nunca usadas son siempre las "más antiguas".
        """
        stmt = (
            select(AccountModel)
            .where(AccountModel.state == "active")
            .order_by(AccountModel.last_used_at.asc().nulls_first())
        )
        result = await self._session.execute(stmt)
        return [to_domain_account(m) for m in result.scalars().all()]
