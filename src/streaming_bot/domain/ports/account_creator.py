"""Puertos para creacion automatizada de cuentas Spotify.

Pipeline:
1. ISmsGateway provee numero temporal (Twilio Programmable SMS).
2. IEmailGateway provee email + recibe verificacion (mail.tm / catchall).
3. IPersonaFactory genera traits coherentes con el pais de la SIM/proxy.
4. IAccountCreator orquesta el signup en Spotify y devuelve `Account` warm-listo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from streaming_bot.domain.entities import Account
from streaming_bot.domain.persona import Persona
from streaming_bot.domain.value_objects import Country


@dataclass(frozen=True, slots=True)
class TempPhoneNumber:
    e164: str  # +51987654321
    country: Country
    rented_at: datetime
    sid: str  # provider-specific id


@dataclass(frozen=True, slots=True)
class SmsMessage:
    from_number: str
    body: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class TempEmailAddress:
    address: str  # alguien@mail.tm
    inbox_id: str
    password: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EmailMessage:
    from_address: str
    subject: str
    body_text: str
    body_html: str
    received_at: datetime


@runtime_checkable
class ISmsGateway(Protocol):
    """Gateway de SMS para verificacion (Twilio Programmable SMS u otro)."""

    async def rent_number(self, *, country: Country) -> TempPhoneNumber: ...

    async def release_number(self, sid: str) -> None: ...

    async def wait_for_sms(
        self,
        *,
        number: TempPhoneNumber,
        timeout_seconds: float = 180.0,
        contains: str = "",
    ) -> SmsMessage | None: ...


@runtime_checkable
class IEmailGateway(Protocol):
    """Gateway de email temporal (mail.tm, catchall propio)."""

    async def create_inbox(self) -> TempEmailAddress: ...

    async def wait_for_email(
        self,
        *,
        inbox: TempEmailAddress,
        timeout_seconds: float = 120.0,
        from_contains: str = "",
        subject_contains: str = "",
    ) -> EmailMessage | None: ...

    async def list_inbox(self, inbox: TempEmailAddress) -> list[EmailMessage]: ...

    async def delete_inbox(self, inbox: TempEmailAddress) -> None: ...


@runtime_checkable
class IPersonaFactory(Protocol):
    """Genera personas coherentes con territorio + dispositivo."""

    def for_country(
        self,
        *,
        country: Country,
        account_id: str,
    ) -> Persona: ...


@dataclass(frozen=True, slots=True)
class AccountCreationRequest:
    country: Country
    persona_seed: str | None = None  # determinismo en tests


@dataclass(frozen=True, slots=True)
class WarmingPolicy:
    """Politica de warming post-signup antes de boostear.

    Una cuenta recien creada no se usa para targets durante N dias.
    Solo navega, escucha camuflaje, y construye historial.
    """

    days_warming: int = 14
    streams_per_day_during_warming: int = 6
    target_streams_per_day_during_warming: int = 0  # cero targets en warming
    must_complete_artist_follows: int = 8
    must_complete_playlist_follows: int = 5
    must_complete_track_likes: int = 12


@runtime_checkable
class IAccountCreator(Protocol):
    """Orquestador del signup. Combina SMS + Email + Browser + Persona."""

    async def create_account(
        self,
        request: AccountCreationRequest,
    ) -> Account: ...

    async def begin_warming(
        self,
        *,
        account: Account,
        policy: WarmingPolicy,
    ) -> None:
        """Marca la cuenta en estado warming. El scheduler la usa solo para camuflaje."""
        ...

    async def complete_warming_if_ready(
        self,
        *,
        account: Account,
        policy: WarmingPolicy,
    ) -> bool:
        """Verifica criterios y promueve la cuenta a active. Devuelve True si promovio."""
        ...
