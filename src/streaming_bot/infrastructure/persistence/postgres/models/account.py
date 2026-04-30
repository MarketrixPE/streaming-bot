"""Modelo ORM de cuenta de Spotify."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from streaming_bot.infrastructure.persistence.postgres.models.base import Base, TimestampMixin


class AccountModel(Base, TimestampMixin):
    """Cuenta de Spotify con credenciales cifradas.

    El campo `password_encrypted` debe llegar ya cifrado por la capa de
    aplicación (Fernet). El esquema no asume cipher concreto: solo TEXT.
    """

    __tablename__ = "accounts"

    # PK reutiliza el UUID4 que el dominio asigna en `Account.new()`.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_encrypted: Mapped[str] = mapped_column(String(1024), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    persona_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("personas.account_id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        # Índice clave para el scheduler: pide cuentas activas ordenadas por
        # última utilización (least-recently-used) en O(log n).
        Index("ix_accounts_state_last_used_at", "state", "last_used_at"),
        # Filtro común: cuentas por país en estado X.
        Index("ix_accounts_country_state", "country", "state"),
    )
