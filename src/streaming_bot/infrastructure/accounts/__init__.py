"""Infraestructura para creacion automatica de cuentas Spotify.

Combina email temporal (mail.tm), SMS (granja propia + 5SIM + Twilio en
failover), generacion de personas (browserforge), y automatizacion de
signup con browser.
"""

from __future__ import annotations

from streaming_bot.infrastructure.accounts.config import AccountsConfig
from streaming_bot.infrastructure.accounts.errors import (
    AccountCreationError,
    EmailGatewayError,
    SmsGatewayError,
)
from streaming_bot.infrastructure.accounts.farm_sms_hub_gateway import (
    FarmSmsHubConfig,
    FarmSmsHubGateway,
)
from streaming_bot.infrastructure.accounts.fivesim_sms_gateway import (
    FiveSimConfig,
    FiveSimGatewayError,
    FiveSimSmsGateway,
)
from streaming_bot.infrastructure.accounts.mail_tm_email_gateway import (
    MailTmEmailGateway,
)
from streaming_bot.infrastructure.accounts.persona_factory import (
    BrowserforgePersonaFactory,
)
from streaming_bot.infrastructure.accounts.sms_gateway_router import SmsGatewayRouter
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
    "FarmSmsHubConfig",
    "FarmSmsHubGateway",
    "FiveSimConfig",
    "FiveSimGatewayError",
    "FiveSimSmsGateway",
    "MailTmEmailGateway",
    "SmsGatewayError",
    "SmsGatewayRouter",
    "SpotifyAccountCreator",
    "StubSmsGateway",
    "TwilioSmsGateway",
]
