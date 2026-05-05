"""Validacion de tokens JWT emitidos por Better Auth.

Better Auth (Next.js dashboard) firma los JWT con RS256 y publica las
claves publicas en ``${BETTER_AUTH_URL}/api/auth/jwks``. Esta API valida
los tokens cargando el JWKS y cacheando el resultado durante un TTL
configurable (default 1h) para no martillear al servicio de auth.

Diseño:
- ``JWTAuthValidator`` no depende de FastAPI: es un servicio puro que
  toma un token string y devuelve un ``AuthenticatedUser`` o lanza
  ``ApiAuthenticationError``. Asi se puede testear sin red.
- El cache de JWKS es protegido con un ``asyncio.Lock`` para evitar
  thundering herd al expirar el TTL.
- El cliente HTTP es opcional para inyectar un fake en tests
  (``httpx.MockTransport`` o stub asincrono).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from jose import ExpiredSignatureError, JWTError, jwt


class ApiAuthenticationError(Exception):
    """Token ausente, malformado, expirado o firmado por otra clave."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class ApiPermissionError(Exception):
    """El usuario esta autenticado pero su rol no permite la operacion."""

    def __init__(self, required_roles: tuple[str, ...], actual_role: str) -> None:
        msg = (
            f"role_not_allowed: required one of {required_roles}, got '{actual_role}'"
        )
        super().__init__(msg)
        self.required_roles = required_roles
        self.actual_role = actual_role


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Identidad resuelta desde el JWT validado."""

    id: str
    role: str
    email: str | None = None
    raw_claims: Mapping[str, Any] | None = None

    @property
    def is_anonymous(self) -> bool:
        return False


class JwksFetcher(Protocol):
    """Hook para inyectar un fetcher fake en tests."""

    async def fetch(self, jwks_url: str) -> dict[str, Any]: ...


class _HttpxJwksFetcher:
    """Implementacion por defecto: usa ``httpx.AsyncClient`` corto-vivido."""

    def __init__(self, *, timeout_seconds: float = 5.0) -> None:
        self._timeout = timeout_seconds

    async def fetch(self, jwks_url: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(jwks_url)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            if not isinstance(data, dict) or "keys" not in data:
                raise ApiAuthenticationError(
                    "jwks_invalid_response",
                    "JWKS URL respondio sin clave 'keys'",
                )
            return data


class JWTAuthValidator:
    """Decoder + verificador de JWT Better Auth con cache de JWKS.

    Args:
        jwks_url: URL absoluta del endpoint JWKS de Better Auth.
        ttl_seconds: tiempo en cache antes de re-fetch.
        algorithms: lista de algoritmos aceptados (default RS256).
        audience / issuer: si vienen no vacios se validan; si vacios se
            ignoran (modo desarrollo, where Better Auth puede emitir
            tokens sin claim aud).
        fetcher: implementacion de JwksFetcher (inyectable en tests).
        clock: callable que devuelve segundos monotonicos; util para
            forzar expiracion en tests.
    """

    def __init__(
        self,
        *,
        jwks_url: str,
        ttl_seconds: int = 3600,
        algorithms: tuple[str, ...] = ("RS256",),
        audience: str = "",
        issuer: str = "",
        fetcher: JwksFetcher | None = None,
        clock: Any | None = None,
    ) -> None:
        if not jwks_url:
            raise ValueError("jwks_url no puede estar vacio")
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds debe ser >= 1")
        if not algorithms:
            raise ValueError("algorithms no puede estar vacio")
        self._jwks_url = jwks_url
        self._ttl = ttl_seconds
        self._algorithms = list(algorithms)
        self._audience = audience or None
        self._issuer = issuer or None
        self._fetcher: JwksFetcher = fetcher or _HttpxJwksFetcher()
        self._clock = clock or time.monotonic
        self._jwks: dict[str, Any] | None = None
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def jwks_url(self) -> str:
        return self._jwks_url

    async def get_jwks(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """Devuelve el JWKS cacheado o lo recarga si caduco."""
        async with self._lock:
            now = float(self._clock())
            stale = self._jwks is None or (now - self._fetched_at) > self._ttl
            if force_refresh or stale:
                self._jwks = await self._fetcher.fetch(self._jwks_url)
                self._fetched_at = now
            assert self._jwks is not None  # invariant tras fetch
            return self._jwks

    async def validate(self, token: str) -> AuthenticatedUser:
        """Decodifica y verifica un token Bearer.

        Raises:
            ApiAuthenticationError: token ausente, expirado, firma
                invalida o claims incompletos.
        """
        if not token:
            raise ApiAuthenticationError("token_empty", "token vacio")
        jwks = await self.get_jwks()
        return self._decode_with_jwks(token, jwks)

    def _decode_with_jwks(
        self,
        token: str,
        jwks: dict[str, Any],
    ) -> AuthenticatedUser:
        options = {
            "verify_aud": self._audience is not None,
            "verify_iss": self._issuer is not None,
        }
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                jwks,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                options=options,
            )
        except ExpiredSignatureError as exc:
            raise ApiAuthenticationError("token_expired", str(exc)) from exc
        except JWTError as exc:
            raise ApiAuthenticationError("token_invalid", str(exc)) from exc

        sub = payload.get("sub")
        if not sub:
            raise ApiAuthenticationError("token_missing_sub", "claim sub ausente")

        role_claim = payload.get("role") or payload.get("user_role") or "viewer"
        role = str(role_claim).lower()

        return AuthenticatedUser(
            id=str(sub),
            role=role,
            email=str(payload["email"]) if payload.get("email") else None,
            raw_claims=payload,
        )
