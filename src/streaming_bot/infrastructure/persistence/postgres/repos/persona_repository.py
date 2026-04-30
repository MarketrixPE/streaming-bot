"""Repositorio Postgres de personas (traits + memory snapshots)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.persona import Persona
from streaming_bot.infrastructure.persistence.postgres.models.persona import (
    PersonaMemorySnapshotModel,
    PersonaModel,
)
from streaming_bot.infrastructure.persistence.postgres.repos.mappers import (
    from_domain_persona,
    memory_snapshot_from_domain,
    to_domain_persona,
)


class PostgresPersonaRepository:
    """Implementación de `IPersonaRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, account_id: str) -> Persona | None:
        """Carga traits + último snapshot de memoria.

        Dos queries separadas (en lugar de JOIN+ORDER BY DESC LIMIT 1) porque
        el subquery por correlated `MAX(snapshot_at)` exige ventana en SQLite
        antes de v3.25 y rompe portabilidad.
        """
        traits_model = await self._session.get(PersonaModel, account_id)
        if traits_model is None:
            return None
        snapshot_stmt = (
            select(PersonaMemorySnapshotModel)
            .where(PersonaMemorySnapshotModel.account_id == account_id)
            .order_by(PersonaMemorySnapshotModel.snapshot_at.desc())
            .limit(1)
        )
        snapshot_result = await self._session.execute(snapshot_stmt)
        snapshot = snapshot_result.scalar_one_or_none()
        return to_domain_persona(traits_model, snapshot)

    async def add(self, persona: Persona) -> None:
        """INSERT de traits + snapshot inicial de la memoria.

        Atomicidad: ambos inserts se quedan en la misma transacción.
        """
        traits_model = from_domain_persona(persona)
        self._session.add(traits_model)
        snapshot = memory_snapshot_from_domain(
            persona,
            snapshot_at=datetime.now(UTC),
        )
        self._session.add(snapshot)
        await self._session.flush()

    async def update_memory(self, persona: Persona) -> None:
        """Append-only: nuevo snapshot + bump `last_session_at_iso`.

        No se tocan los traits: son inmutables por diseño del dominio.
        """
        traits_model = await self._session.get(PersonaModel, persona.account_id)
        if traits_model is None:
            raise DomainError(
                f"persona no encontrada: {persona.account_id}",
            )
        now = datetime.now(UTC)
        snapshot = memory_snapshot_from_domain(persona, snapshot_at=now)
        self._session.add(snapshot)
        traits_model.last_session_at_iso = persona.last_session_at_iso or now.isoformat()
        await self._session.flush()

    async def list_all(self) -> list[Persona]:
        """Listado completo (uso administrativo).

        Para cada persona se hace una sub-query del snapshot más reciente.
        Costoso para N grande; aceptable porque `list_all` no está en el
        camino caliente del scheduler.
        """
        result = await self._session.execute(select(PersonaModel))
        traits_models = result.scalars().all()
        personas: list[Persona] = []
        for traits in traits_models:
            snapshot_stmt = (
                select(PersonaMemorySnapshotModel)
                .where(PersonaMemorySnapshotModel.account_id == traits.account_id)
                .order_by(PersonaMemorySnapshotModel.snapshot_at.desc())
                .limit(1)
            )
            snapshot_result = await self._session.execute(snapshot_stmt)
            snapshot = snapshot_result.scalar_one_or_none()
            personas.append(to_domain_persona(traits, snapshot))
        return personas
