"""Entidades del dominio: tienen identidad y ciclo de vida."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from streaming_bot.domain.value_objects import Country


@dataclass(frozen=True, slots=True)
class AccountStatus:
    """Estado de la cuenta. Frozen para forzar transiciones explícitas."""

    state: str  # "active" | "banned" | "rate_limited"
    reason: str | None = None

    @classmethod
    def active(cls) -> AccountStatus:
        return cls(state="active")

    @classmethod
    def banned(cls, reason: str) -> AccountStatus:
        return cls(state="banned", reason=reason)

    @classmethod
    def rate_limited(cls, reason: str) -> AccountStatus:
        return cls(state="rate_limited", reason=reason)

    @property
    def is_usable(self) -> bool:
        return self.state == "active"


@dataclass(slots=True)
class Account:
    """Cuenta de usuario para automatizar.

    Mutable controladamente: solo el repositorio puede actualizar `status`
    y `last_used_at` mediante métodos explícitos.
    """

    id: str
    username: str
    password: str  # cifrado en repositorio; aquí en claro solo en memoria
    country: Country
    status: AccountStatus = field(default_factory=AccountStatus.active)
    last_used_at: datetime | None = None

    @classmethod
    def new(cls, *, username: str, password: str, country: Country) -> Account:
        return cls(id=str(uuid4()), username=username, password=password, country=country)

    def mark_used(self) -> None:
        self.last_used_at = datetime.now(UTC)

    def deactivate(self, reason: str) -> None:
        self.status = AccountStatus.banned(reason)


@dataclass(frozen=True, slots=True)
class StreamJob:
    """Una unidad de trabajo: cuenta + URL objetivo."""

    job_id: str
    account_id: str
    target_url: str

    @classmethod
    def new(cls, *, account_id: str, target_url: str) -> StreamJob:
        return cls(job_id=str(uuid4()), account_id=account_id, target_url=target_url)
