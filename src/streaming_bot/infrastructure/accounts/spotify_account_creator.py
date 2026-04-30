"""Orquestador de signup completo: email + SMS + browser + persona."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import uuid4

import structlog

from streaming_bot.domain.entities import Account
from streaming_bot.domain.ports import (
    IAccountRepository,
    IBrowserDriver,
    IFingerprintGenerator,
    IProxyProvider,
    ISessionStore,
)
from streaming_bot.domain.ports.account_creator import (
    AccountCreationRequest,
    IEmailGateway,
    IPersonaFactory,
    ISmsGateway,
    WarmingPolicy,
)
from streaming_bot.infrastructure.accounts.config import AccountsConfig
from streaming_bot.infrastructure.accounts.errors import AccountCreationError

logger = structlog.get_logger("streaming_bot.accounts.creator")


class SpotifyAccountCreator:
    """Implementación de IAccountCreator. Orquesta signup end-to-end.

    Flow:
    1. Acquire proxy + fingerprint
    2. Create email inbox + rent SMS number
    3. Open browser session y navegar a signup
    4. Llenar form (email, password, display_name, DOB)
    5. Esperar email verification
    6. Si Spotify pide SMS, usar el número rentado
    7. Generar persona coherente
    8. Persistir Account + storage_state
    """

    def __init__(
        self,
        *,
        sms: ISmsGateway,
        email: IEmailGateway,
        personas: IPersonaFactory,
        accounts: IAccountRepository,
        proxies: IProxyProvider,
        fingerprints: IFingerprintGenerator,
        sessions: ISessionStore,
        browser: IBrowserDriver,
        config: AccountsConfig,
        logger: structlog.BoundLogger | None = None,
    ) -> None:
        self._sms = sms
        self._email = email
        self._personas = personas
        self._accounts = accounts
        self._proxies = proxies
        self._fingerprints = fingerprints
        self._sessions = sessions
        self._browser = browser
        self._config = config
        self._log = logger or structlog.get_logger("streaming_bot.accounts.creator")

        # Estado de warming en memoria (TODO: persistir cuando exista tabla)
        self._warming_state: dict[str, dict[str, datetime | int]] = {}

    async def create_account(  # noqa: PLR0915
        self,
        request: AccountCreationRequest,
    ) -> Account:
        """Crea una cuenta de Spotify end-to-end."""
        log = self._log.bind(action="create_account", country=request.country.value)
        log.info("starting_account_creation")

        email_inbox = None
        phone = None

        try:
            # 1. Acquire proxy + fingerprint
            proxy = await self._proxies.acquire(country=request.country)
            fingerprint = self._fingerprints.coherent_for(proxy, fallback_country=request.country)
            log.debug("proxy_fingerprint_ready", proxy_country=proxy.country if proxy else None)

            # 2. Create email inbox
            email_inbox = await self._email.create_inbox()
            log.info("email_inbox_created", address=email_inbox.address)

            # 3. Rent SMS number
            phone = await self._sms.rent_number(country=request.country)
            log.info("sms_number_rented", number=phone.e164)

            # 4. Generar credenciales
            password = secrets.token_urlsafe(16)
            display_name = f"User{secrets.randbelow(99999):05d}"

            # Fecha de nacimiento (18-35 años atrás)
            current_year = datetime.now(UTC).year
            birth_year = current_year - secrets.randbelow(18) - 18
            birth_month = secrets.randbelow(12) + 1
            birth_day = secrets.randbelow(28) + 1  # Evitar edge cases de feb/31

            # 5. Open browser session
            async with self._browser.session(
                proxy=proxy,
                fingerprint=fingerprint,
                storage_state=None,
            ) as session:
                log.info("browser_session_opened")

                # 6. Navegar a signup
                await session.goto(self._config.spotify_signup_url)
                log.debug("navigated_to_signup")

                # TODO: Ajustar selectores con DOM real cuando se ejecute por primera vez
                # Estos son selectores comunes, pero pueden cambiar
                try:
                    # Llenar email
                    await session.fill('input[name="email"]', email_inbox.address)
                    await session.fill('input[type="password"]', password)
                    await session.fill('input[name="displayName"]', display_name)

                    # Llenar DOB (puede tener 3 dropdowns o inputs separados)
                    # TODO: verificar estructura real del form
                    await session.fill('input[name="month"]', str(birth_month))
                    await session.fill('input[name="day"]', str(birth_day))
                    await session.fill('input[name="year"]', str(birth_year))

                    # Marcar términos
                    await session.click('input[type="checkbox"]')  # TODO: selector específico

                    # Submit
                    await session.click('button[type="submit"]')
                    log.info("signup_form_submitted")

                except Exception as e:
                    log.error("form_fill_failed", error=str(e))
                    msg = f"Failed to fill signup form: {e}"
                    raise AccountCreationError(msg) from e

                # 7. Esperar email de verificación
                log.info("waiting_for_verification_email")
                verification_email = await self._email.wait_for_email(
                    inbox=email_inbox,
                    from_contains="spotify.com",
                    subject_contains="confirm",
                    timeout_seconds=180.0,
                )

                if not verification_email:
                    msg = "Email verification timeout"
                    log.error("email_verification_timeout")
                    raise AccountCreationError(msg)

                # TODO: Extraer URL de confirmación del body y abrirla
                # Por ahora, asumimos que el email contiene un link
                log.info("verification_email_received")

                # 8. Si Spotify pide SMS verification (detectar en la página)
                # TODO: Implementar detección de SMS verification en el DOM
                # Por ahora, intentamos esperar SMS como ejemplo
                try:
                    log.info("checking_for_sms_verification")
                    # Esto es placeholder: en la práctica necesitamos detectar
                    # si la página pide SMS
                    sms_message = await self._sms.wait_for_sms(
                        number=phone,
                        contains="Spotify",
                        timeout_seconds=60.0,
                    )
                    if sms_message:
                        log.info("sms_verification_received", code_length=len(sms_message.body))
                        # TODO: Inyectar código en el form
                except Exception as e:
                    log.warning("sms_verification_optional_failed", error=str(e))

                # 9. Verificar si hay captcha
                page_content = await session.content()
                if "captcha" in page_content.lower() or "recaptcha" in page_content.lower():
                    msg = "captcha_detected: human_intervention_needed"
                    log.error("captcha_detected")
                    raise AccountCreationError(msg)

                # 10. Generar persona
                account_id = str(uuid4())
                persona = self._personas.for_country(
                    country=request.country,
                    account_id=account_id,
                )
                log.info("persona_generated", engagement=persona.traits.engagement_level.value)

                # 11. Construir Account
                account = Account.new(
                    username=email_inbox.address,
                    password=password,
                    country=request.country,
                )
                # Forzar el ID que generamos para la persona
                account.id = account_id

                # 12. Persistir account
                await self._accounts.update(account)
                log.info("account_persisted", account_id=account.id)

                # 13. Guardar storage_state
                storage_state = await session.storage_state()
                await self._sessions.save(account.id, storage_state)
                log.info("session_saved")

                return account

        except AccountCreationError:
            raise
        except Exception as e:
            log.error("create_account_failed", error=str(e))
            msg = f"Account creation failed: {e}"
            raise AccountCreationError(msg) from e
        finally:
            # Cleanup: delete email inbox y release phone
            if email_inbox:
                try:
                    await self._email.delete_inbox(email_inbox)
                except Exception as e:
                    log.warning("email_cleanup_failed", error=str(e))
            if phone:
                try:
                    await self._sms.release_number(phone.sid)
                except Exception as e:
                    log.warning("sms_cleanup_failed", error=str(e))

    async def begin_warming(
        self,
        *,
        account: Account,
        policy: WarmingPolicy,
    ) -> None:
        """Marca la cuenta en estado warming.

        POR AHORA: implementa SOLO un log + dict en memoria.
        TODO: persistir en tabla cuando exista el schema.
        """
        log = self._log.bind(action="begin_warming", account_id=account.id)
        self._warming_state[account.id] = {
            "warming_started_at": datetime.now(UTC),
            "policy_days": policy.days_warming,
        }
        log.info("warming_started", policy_days=policy.days_warming)

    async def complete_warming_if_ready(
        self,
        *,
        account: Account,
        policy: WarmingPolicy,
    ) -> bool:
        """Verifica si la cuenta completó el warming period.

        POR AHORA: solo verifica días transcurridos desde warming_started_at.
        TODO: verificar follows/likes cuando exista la integración con Spotify API.
        """
        log = self._log.bind(action="complete_warming_if_ready", account_id=account.id)

        warming_data = self._warming_state.get(account.id)
        if not warming_data:
            log.warning("warming_not_started")
            return False

        warming_started = warming_data["warming_started_at"]
        assert isinstance(warming_started, datetime)
        days_elapsed = (datetime.now(UTC) - warming_started).days

        if days_elapsed >= policy.days_warming:
            log.info("warming_complete", days_elapsed=days_elapsed)
            # TODO: verificar también artist follows, playlist follows, track likes
            return True

        log.debug(
            "warming_in_progress",
            days_elapsed=days_elapsed,
            days_required=policy.days_warming,
        )
        return False
