"""Configuración para el subsistema de account creation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AccountsConfig(BaseModel):
    """Configuración de gateways y servicios externos para account creation."""

    # Twilio SMS gateway
    twilio_account_sid: str = Field(default="")
    twilio_auth_token: str = Field(default="")
    twilio_phone_pool_friendly_name: str = Field(default="spotify-pool")

    # Mail.tm email gateway
    mail_tm_base_url: str = Field(default="https://api.mail.tm")
    mail_tm_request_timeout_seconds: float = Field(default=15.0)

    # Spotify signup
    spotify_signup_url: str = Field(default="https://www.spotify.com/signup")
