"""Tests para los factories nuevos del ProductionContainer."""

from __future__ import annotations

import pytest

from streaming_bot.config import AccountsApiSettings, Settings, SpotifyApiSettings
from streaming_bot.container import ProductionContainer


def test_make_spotify_client_missing_credentials() -> None:
    """Verifica que make_spotify_client falle si no hay credentials."""
    settings = Settings(
        spotify=SpotifyApiSettings(client_id="", client_secret=""),
    )
    container = ProductionContainer.build(settings)

    with pytest.raises(RuntimeError, match="spotify_credentials_missing"):
        container.make_spotify_client()


def test_make_spotify_client_config_validation() -> None:
    """Verifica que settings cargue correctamente las credenciales."""
    settings = Settings(
        spotify=SpotifyApiSettings(
            client_id="test_client_id",
            client_secret="test_client_secret",
        ),
    )
    # Solo verificamos configuracion, no instanciamos el container
    assert settings.spotify.client_id != ""
    assert settings.spotify.client_secret != ""


def test_make_account_creator_config_validation() -> None:
    """Verifica que settings configure correctamente use_stub_sms."""
    settings_stub = Settings(
        accounts=AccountsApiSettings(
            use_stub_sms=True,
            twilio_account_sid="",
        ),
    )
    assert settings_stub.accounts.use_stub_sms is True

    settings_twilio = Settings(
        accounts=AccountsApiSettings(
            use_stub_sms=False,
            twilio_account_sid="test_sid",
        ),
    )
    assert settings_twilio.accounts.use_stub_sms is False
    assert settings_twilio.accounts.twilio_account_sid == "test_sid"
