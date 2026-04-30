"""Excepciones específicas del subsistema de account creation."""

from __future__ import annotations


class EmailGatewayError(Exception):
    """Error en operaciones del email gateway (mail.tm u otro)."""


class SmsGatewayError(Exception):
    """Error en operaciones del SMS gateway (Twilio u otro)."""


class AccountCreationError(Exception):
    """Error en el flujo de creación de cuenta (signup, verificación, etc.)."""
