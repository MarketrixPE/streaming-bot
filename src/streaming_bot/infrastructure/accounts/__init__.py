"""Infraestructura para creación automática de cuentas Spotify.

Epic 2: Combina email temporal (mail.tm), SMS (Twilio), generación de personas
(browserforge), y automatización de signup con browser.
"""

from __future__ import annotations

from streaming_bot.infrastructure.accounts.config import AccountsConfig
from streaming_bot.infrastructure.accounts.errors import (
    AccountCreationError,
    EmailGatewayError,
    SmsGatewayError,
)
from streaming_bot.infrastructure.accounts.mail_tm_email_gateway import (
    MailTmEmailGateway,
)
from streaming_bot.infrastructure.accounts.persona_factory import (
    BrowserforgePersonaFactory,
)
from streaming_bot.infrastructure.accounts.spotify_account_creator import (
    SpotifyAccountCreator,
)
from streaming_bot.infrastructure.accounts.stub_sms_gateway import StubSmsGateway
from streaming_bot.infrastructure.accounts.twilio_sms_gateway import (
    TwilioSmsGateway,
)

__all__ = [
    "AccountCreationError",
    "AccountsConfig",
    "BrowserforgePersonaFactory",
    "EmailGatewayError",
    "MailTmEmailGateway",
    "SmsGatewayError",
    "SpotifyAccountCreator",
    "StubSmsGateway",
    "TwilioSmsGateway",
]
