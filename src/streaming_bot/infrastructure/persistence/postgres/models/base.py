"""Base declarativa, mixin de timestamps y helper de PK ULID.

Decisiones:
- `MetaData` con `naming_convention` para que Alembic genere nombres de
  constraint deterministas (importante en upgrades que renombran índices).
- `TimestampMixin` usa `server_default=func.now()` para que la BD sea la
  autoridad temporal aún cuando dos workers escriban sin reloj sincronizado.
- `ulid_pk` permite generar IDs lexicográficamente ordenables (útil para
  paginación por id y para que los índices B-tree mantengan localidad).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from ulid import ULID

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base declarativa única para todos los modelos del esquema."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def ulid_pk() -> Mapped[str]:
    """Helper para columnas PK con ULID (26 chars) generado en cliente.

    Útil para tablas cuyo dominio no expone `id` propio (history, sessions,
    snapshots). Las tablas que reflejan entidades con `id` UUID4 ya generado
    por el dominio definen su PK explícitamente con `String(36)`.
    """
    return mapped_column(
        String(26),
        primary_key=True,
        default=lambda: str(ULID()),
    )


class TimestampMixin:
    """Mixin con `created_at`/`updated_at` autogestionados por la BD."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )
