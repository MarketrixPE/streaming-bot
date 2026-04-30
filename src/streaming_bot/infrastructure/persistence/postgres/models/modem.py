"""Modelo ORM del pool de modems 4G/5G residenciales."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from streaming_bot.infrastructure.persistence.postgres.models.base import Base, TimestampMixin


class ModemModel(Base, TimestampMixin):
    """Modem físico con su SIM y contadores diarios.

    `imei` e `iccid` son únicos: dos filas con la misma SIM serían un bug
    operativo (riesgo de doble-asignación a cuentas distintas en paralelo).
    """

    __tablename__ = "modems"

    # PK reutiliza UUID4 del dominio (`Modem.new()`).
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    imei: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    iccid: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    serial_port: Mapped[str] = mapped_column(String(64), nullable=False)
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    sim_country: Mapped[str] = mapped_column(String(2), nullable=False)

    state: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    current_public_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    last_rotation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    accounts_used_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    streams_served_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    flagged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str] = mapped_column(String(1024), nullable=False, default="")

    max_accounts_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    max_streams_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=250)
    rotation_cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    use_cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)

    __table_args__ = (
        # El asignador de modems pide modems disponibles por país.
        Index("ix_modems_country_state", "sim_country", "state"),
        Index("ix_modems_state_last_used", "state", "last_used_at"),
    )
