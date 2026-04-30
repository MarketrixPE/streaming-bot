"""Excepciones del dominio. Jerarquía con propósito claro para retry/no-retry."""

from __future__ import annotations


class DomainError(Exception):
    """Base de todas las excepciones del dominio."""


class TransientError(DomainError):
    """Errores reintentables (red caída, timeout, proxy muerto)."""


class PermanentError(DomainError):
    """Errores NO reintentables (credenciales inválidas, cuenta baneada)."""


class AuthenticationError(PermanentError):
    """Login falló por credenciales/2FA/captcha."""


class AccountBlockedError(PermanentError):
    """La cuenta fue bloqueada por el proveedor."""


class ProxyUnavailableError(TransientError):
    """No hay proxies sanos disponibles."""


class BrowserCrashError(TransientError):
    """El browser/contexto crasheó."""


class TargetSiteError(TransientError):
    """Error en el sitio objetivo (5xx, layout cambió, elemento no encontrado)."""
