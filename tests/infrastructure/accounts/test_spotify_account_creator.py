"""Tests para SpotifyAccountCreator con fakes de todos los puertos."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
import structlog

from streaming_bot.domain.entities import Account
from streaming_bot.domain.persona import (
    BehaviorProbabilities,
    DeviceType,
    EngagementLevel,
    MouseProfile,
    Persona,
    PersonaMemory,
    PersonaTraits,
    PlatformProfile,
    SessionPattern,
    TypingProfile,
)
from streaming_bot.domain.ports.account_creator import (
    AccountCreationRequest,
    EmailMessage,
    SmsMessage,
    TempEmailAddress,
    TempPhoneNumber,
    WarmingPolicy,
)
from streaming_bot.domain.value_objects import (
    Country,
    Fingerprint,
    GeoCoordinate,
    ProxyEndpoint,
)
from streaming_bot.infrastructure.accounts.config import AccountsConfig
from streaming_bot.infrastructure.accounts.errors import (
    AccountCreationError,
    SmsGatewayError,
)
from streaming_bot.infrastructure.accounts.spotify_account_creator import (
    SpotifyAccountCreator,
)

# --- Fakes de todos los puertos ---


class FakeEmailGateway:
    """Fake IEmailGateway que no hace red."""

    def __init__(self) -> None:
        self.inboxes_created: list[TempEmailAddress] = []
        self.deleted_inboxes: list[str] = []

    async def create_inbox(self) -> TempEmailAddress:
        inbox = TempEmailAddress(
            address="test@example.com",
            inbox_id="inbox123",
            password="secret",
            created_at=datetime.now(UTC),
        )
        self.inboxes_created.append(inbox)
        return inbox

    async def wait_for_email(
        self,
        *,
        inbox: TempEmailAddress,
        timeout_seconds: float = 120.0,
        from_contains: str = "",
        subject_contains: str = "",
    ) -> EmailMessage | None:
        return EmailMessage(
            from_address="no-reply@spotify.com",
            subject="Confirm your email",
            body_text="Click here: https://spotify.com/confirm/abc",
            body_html=["<p>Click here</p>"],
            received_at=datetime.now(UTC),
        )

    async def list_inbox(self, inbox: TempEmailAddress) -> list[EmailMessage]:
        return []

    async def delete_inbox(self, inbox: TempEmailAddress) -> None:
        self.deleted_inboxes.append(inbox.inbox_id)


class FakeSmsGateway:
    """Fake ISmsGateway que no hace red."""

    def __init__(self, *, fail_on_rent: bool = False) -> None:
        self.numbers_rented: list[TempPhoneNumber] = []
        self.numbers_released: list[str] = []
        self._fail_on_rent = fail_on_rent

    async def rent_number(self, *, country: Country) -> TempPhoneNumber:
        if self._fail_on_rent:
            raise SmsGatewayError("twilio_credentials_missing")

        phone = TempPhoneNumber(
            e164="+51987654321",
            country=country,
            rented_at=datetime.now(UTC),
            sid="PN123abc",
        )
        self.numbers_rented.append(phone)
        return phone

    async def release_number(self, sid: str) -> None:
        self.numbers_released.append(sid)

    async def wait_for_sms(
        self,
        *,
        number: TempPhoneNumber,
        timeout_seconds: float = 180.0,
        contains: str = "",
    ) -> SmsMessage | None:
        return None  # Spotify no pide SMS en este test


class FakePersonaFactory:
    """Fake IPersonaFactory que genera persona simple."""

    def for_country(self, *, country: Country, account_id: str) -> Persona:
        traits = PersonaTraits(
            engagement_level=EngagementLevel.CASUAL,
            preferred_genres=("reggaeton", "trap latino"),
            preferred_session_hour_local=(18, 22),
            device=DeviceType.DESKTOP_CHROME,
            platform=PlatformProfile.WINDOWS_DESKTOP,
            ui_language="es-PE",
            timezone="America/Lima",
            country=country,
            behaviors=BehaviorProbabilities.for_engagement_level(EngagementLevel.CASUAL),
            typing=TypingProfile(),
            mouse=MouseProfile(),
            session=SessionPattern(),
        )

        return Persona(account_id=account_id, traits=traits, memory=PersonaMemory())


class FakeAccountRepository:
    """Fake IAccountRepository que guarda en memoria."""

    def __init__(self) -> None:
        self.accounts: dict[str, Account] = {}

    async def all(self) -> list[Account]:
        return list(self.accounts.values())

    async def get(self, account_id: str) -> Account:
        return self.accounts[account_id]

    async def update(self, account: Account) -> None:
        self.accounts[account.id] = account


class FakeProxyProvider:
    """Fake IProxyProvider que devuelve proxy simple."""

    async def acquire(self, *, country: Country | None = None) -> ProxyEndpoint | None:
        return ProxyEndpoint(
            scheme="http",
            host="proxy.example.com",
            port=8080,
            country=country,
        )

    async def report_failure(self, proxy: ProxyEndpoint, reason: str) -> None:
        pass

    async def report_success(self, proxy: ProxyEndpoint) -> None:
        pass


class FakeFingerprintGenerator:
    """Fake IFingerprintGenerator que devuelve fingerprint coherente."""

    def coherent_for(
        self,
        proxy: ProxyEndpoint | None,
        *,
        fallback_country: Country = Country.US,
    ) -> Fingerprint:
        country = proxy.country if proxy and proxy.country else fallback_country
        return Fingerprint(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            locale="es-PE",
            timezone_id="America/Lima",
            geolocation=GeoCoordinate(latitude=-12.0464, longitude=-77.0428),
            country=country,
        )


class FakeSessionStore:
    """Fake ISessionStore que guarda en memoria."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}

    async def load(self, account_id: str) -> dict[str, Any] | None:
        return self.sessions.get(account_id)

    async def save(self, account_id: str, state: dict[str, Any]) -> None:
        self.sessions[account_id] = state

    async def delete(self, account_id: str) -> None:
        self.sessions.pop(account_id, None)


class FakeBrowserSession:
    """Fake IBrowserSession que simula interacciones."""

    def __init__(self, *, has_captcha: bool = False) -> None:
        self._has_captcha = has_captcha

    async def goto(self, url: str, *, wait_until: str = "networkidle") -> None:
        pass

    async def fill(self, selector: str, value: str) -> None:
        pass

    async def click(self, selector: str) -> None:
        pass

    async def wait_for_selector(self, selector: str, *, timeout_ms: int = 30000) -> None:
        pass

    async def evaluate(self, expression: str) -> Any:
        return None

    async def screenshot(self, path: str) -> None:
        pass

    async def content(self) -> str:
        if self._has_captcha:
            return "<html><body>Please solve the captcha</body></html>"
        return "<html><body>Welcome to Spotify</body></html>"

    async def storage_state(self) -> dict[str, Any]:
        return {
            "cookies": [{"name": "sp_t", "value": "abc123", "domain": ".spotify.com"}],
            "origins": [],
        }


class FakeBrowserDriver:
    """Fake IBrowserDriver que devuelve sesiones."""

    def __init__(self, *, has_captcha: bool = False) -> None:
        self._has_captcha = has_captcha

    @asynccontextmanager
    async def session(
        self,
        *,
        proxy: ProxyEndpoint | None,
        fingerprint: Fingerprint,
        storage_state: dict[str, Any] | None = None,
    ) -> Any:
        yield FakeBrowserSession(has_captcha=self._has_captcha)

    async def close(self) -> None:
        pass


# --- Tests ---


class TestSpotifyAccountCreator:
    """Tests de SpotifyAccountCreator con fakes de todos los puertos."""

    @pytest.fixture
    def fakes(self) -> dict[str, Any]:
        """Devuelve dict con todos los fakes."""
        return {
            "email": FakeEmailGateway(),
            "sms": FakeSmsGateway(),
            "personas": FakePersonaFactory(),
            "accounts": FakeAccountRepository(),
            "proxies": FakeProxyProvider(),
            "fingerprints": FakeFingerprintGenerator(),
            "sessions": FakeSessionStore(),
            "browser": FakeBrowserDriver(),
        }

    @pytest.fixture
    def config(self) -> AccountsConfig:
        """Config de tests."""
        return AccountsConfig(
            spotify_signup_url="https://www.spotify.com/signup",
        )

    @pytest.mark.asyncio
    async def test_create_account_end_to_end(
        self, fakes: dict[str, Any], config: AccountsConfig
    ) -> None:
        """Verifica el flujo completo de creación de cuenta."""
        creator = SpotifyAccountCreator(
            sms=fakes["sms"],
            email=fakes["email"],
            personas=fakes["personas"],
            accounts=fakes["accounts"],
            proxies=fakes["proxies"],
            fingerprints=fakes["fingerprints"],
            sessions=fakes["sessions"],
            browser=fakes["browser"],
            config=config,
            logger=structlog.get_logger(),
        )

        request = AccountCreationRequest(country=Country.PE)
        account = await creator.create_account(request)

        # Verificar cuenta creada
        assert account.id
        assert account.username == "test@example.com"
        assert account.password
        assert account.country == Country.PE

        # Verificar que se usaron los gateways
        assert len(fakes["email"].inboxes_created) == 1
        assert len(fakes["email"].deleted_inboxes) == 1  # cleanup
        assert len(fakes["sms"].numbers_rented) == 1
        assert len(fakes["sms"].numbers_released) == 1  # cleanup

        # Verificar persistencia
        assert account.id in fakes["accounts"].accounts
        assert account.id in fakes["sessions"].sessions

    @pytest.mark.asyncio
    async def test_captcha_raises_account_creation_error(
        self, fakes: dict[str, Any], config: AccountsConfig
    ) -> None:
        """Verifica que si hay captcha, se lanza AccountCreationError."""
        fakes["browser"] = FakeBrowserDriver(has_captcha=True)

        creator = SpotifyAccountCreator(
            sms=fakes["sms"],
            email=fakes["email"],
            personas=fakes["personas"],
            accounts=fakes["accounts"],
            proxies=fakes["proxies"],
            fingerprints=fakes["fingerprints"],
            sessions=fakes["sessions"],
            browser=fakes["browser"],
            config=config,
            logger=structlog.get_logger(),
        )

        request = AccountCreationRequest(country=Country.PE)

        with pytest.raises(AccountCreationError, match="captcha_detected"):
            await creator.create_account(request)

    @pytest.mark.asyncio
    async def test_twilio_creds_missing_raises_on_first_use(
        self, fakes: dict[str, Any], config: AccountsConfig
    ) -> None:
        """Verifica que si Twilio no tiene creds, lanza SmsGatewayError."""
        fakes["sms"] = FakeSmsGateway(fail_on_rent=True)

        creator = SpotifyAccountCreator(
            sms=fakes["sms"],
            email=fakes["email"],
            personas=fakes["personas"],
            accounts=fakes["accounts"],
            proxies=fakes["proxies"],
            fingerprints=fakes["fingerprints"],
            sessions=fakes["sessions"],
            browser=fakes["browser"],
            config=config,
            logger=structlog.get_logger(),
        )

        request = AccountCreationRequest(country=Country.PE)

        with pytest.raises(AccountCreationError):
            await creator.create_account(request)

    @pytest.mark.asyncio
    async def test_begin_warming_tracks_state(
        self, fakes: dict[str, Any], config: AccountsConfig
    ) -> None:
        """Verifica que begin_warming marca la cuenta en warming."""
        creator = SpotifyAccountCreator(
            sms=fakes["sms"],
            email=fakes["email"],
            personas=fakes["personas"],
            accounts=fakes["accounts"],
            proxies=fakes["proxies"],
            fingerprints=fakes["fingerprints"],
            sessions=fakes["sessions"],
            browser=fakes["browser"],
            config=config,
            logger=structlog.get_logger(),
        )

        account = Account.new(
            username="test@example.com",
            password="pass123",
            country=Country.PE,
        )
        policy = WarmingPolicy(days_warming=14)

        await creator.begin_warming(account=account, policy=policy)

        # Verificar estado interno
        assert account.id in creator._warming_state
        assert "warming_started_at" in creator._warming_state[account.id]

    @pytest.mark.asyncio
    async def test_complete_warming_if_ready_checks_days(
        self, fakes: dict[str, Any], config: AccountsConfig
    ) -> None:
        """Verifica que complete_warming_if_ready devuelve False si no han pasado días."""
        creator = SpotifyAccountCreator(
            sms=fakes["sms"],
            email=fakes["email"],
            personas=fakes["personas"],
            accounts=fakes["accounts"],
            proxies=fakes["proxies"],
            fingerprints=fakes["fingerprints"],
            sessions=fakes["sessions"],
            browser=fakes["browser"],
            config=config,
            logger=structlog.get_logger(),
        )

        account = Account.new(
            username="test@example.com",
            password="pass123",
            country=Country.PE,
        )
        policy = WarmingPolicy(days_warming=14)

        await creator.begin_warming(account=account, policy=policy)

        # Inmediatamente después, no debe estar listo
        is_ready = await creator.complete_warming_if_ready(account=account, policy=policy)

        assert is_ready is False
