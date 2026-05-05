"""Tests del modulo de auth: JWT validation, RBAC y manejo de errores HTTP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwk, jwt
from jose.utils import long_to_base64

from streaming_bot.config import Settings
from streaming_bot.presentation.api.auth import (
    ApiAuthenticationError,
    ApiPermissionError,
    JWTAuthValidator,
)
from streaming_bot.presentation.api.dependencies import get_current_user
from tests.presentation.conftest import _make_user, build_app_with_overrides

try:  # cryptography es opcional, pero RS256 lo requiere y python-jose lo trae como extra.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    HAS_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover
    HAS_CRYPTOGRAPHY = False
    serialization = None  # type: ignore[assignment]
    rsa = None  # type: ignore[assignment]


def _generate_rsa_keypair() -> tuple[Any, dict[str, Any]]:
    """Devuelve (private_pem, jwks_dict) para firmar/verificar tokens RS256."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_numbers = private_key.public_key().public_numbers()
    jwk_entry = {
        "kty": "RSA",
        "kid": "test-key",
        "alg": "RS256",
        "use": "sig",
        "n": long_to_base64(public_numbers.n).decode("ascii"),
        "e": long_to_base64(public_numbers.e).decode("ascii"),
    }
    return private_pem, {"keys": [jwk_entry]}


class _StubFetcher:
    def __init__(self, jwks: dict[str, Any]) -> None:
        self.jwks = jwks
        self.calls = 0

    async def fetch(self, jwks_url: str) -> dict[str, Any]:
        self.calls += 1
        return self.jwks


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_CRYPTOGRAPHY, reason="cryptography no disponible")
async def test_jwt_validator_decodes_valid_token() -> None:
    private_pem, jwks = _generate_rsa_keypair()
    fetcher = _StubFetcher(jwks)
    validator = JWTAuthValidator(jwks_url="http://test/jwks", fetcher=fetcher)

    payload = {
        "sub": "user-1",
        "email": "u1@example.com",
        "role": "admin",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": "test-key"})
    user = await validator.validate(token)
    assert user.id == "user-1"
    assert user.role == "admin"
    assert user.email == "u1@example.com"
    assert fetcher.calls == 1

    # Segunda llamada usa cache (no debe re-fetchear).
    await validator.validate(token)
    assert fetcher.calls == 1


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_CRYPTOGRAPHY, reason="cryptography no disponible")
async def test_jwt_validator_rejects_expired_token() -> None:
    private_pem, jwks = _generate_rsa_keypair()
    validator = JWTAuthValidator(jwks_url="http://test/jwks", fetcher=_StubFetcher(jwks))
    payload = {
        "sub": "user-x",
        "role": "viewer",
        "exp": datetime.now(UTC) - timedelta(minutes=1),
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": "test-key"})
    with pytest.raises(ApiAuthenticationError) as exc:
        await validator.validate(token)
    assert exc.value.code == "token_expired"


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_CRYPTOGRAPHY, reason="cryptography no disponible")
async def test_jwt_validator_rejects_wrong_signature() -> None:
    _, real_jwks = _generate_rsa_keypair()
    other_private, _ = _generate_rsa_keypair()
    validator = JWTAuthValidator(
        jwks_url="http://test/jwks",
        fetcher=_StubFetcher(real_jwks),
    )
    payload = {
        "sub": "user-y",
        "role": "operator",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    token = jwt.encode(payload, other_private, algorithm="RS256", headers={"kid": "test-key"})
    with pytest.raises(ApiAuthenticationError) as exc:
        await validator.validate(token)
    assert exc.value.code == "token_invalid"


@pytest.mark.asyncio
async def test_jwt_validator_rejects_missing_sub() -> None:
    jwks = {
        "keys": [
            jwk.construct("supersecreto", algorithm="HS256").to_dict(),
        ]
    }
    jwks["keys"][0]["alg"] = "HS256"
    jwks["keys"][0]["kid"] = "test-key"
    validator = JWTAuthValidator(
        jwks_url="http://test/jwks",
        fetcher=_StubFetcher(jwks),
        algorithms=("HS256",),
    )
    token = jwt.encode(
        {"role": "viewer", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        "supersecreto",
        algorithm="HS256",
        headers={"kid": "test-key"},
    )
    with pytest.raises(ApiAuthenticationError) as exc:
        await validator.validate(token)
    assert exc.value.code == "token_missing_sub"


@pytest.mark.asyncio
async def test_protected_route_returns_401_without_token(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
) -> None:
    """Sin override de get_current_user, el handler exige Bearer header."""
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=None,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/tracks")
    assert response.status_code == 401
    body = response.json()
    assert body["error_code"] == "missing_bearer_token"
    assert response.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_require_role_blocks_insufficient_role(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
) -> None:
    """Un viewer puede leer; verificamos que el RBAC permite roles esperados.

    El piloto v1 expone catalogo a viewer/operator/admin, asi que un user
    con rol 'guest' debe ser rechazado con 403.
    """
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=_make_user("viewer"),
    )
    # Cambiamos a un rol no permitido tras construccion
    app.dependency_overrides[get_current_user] = lambda: _make_user("guest")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/tracks")
    assert response.status_code == 403
    body = response.json()
    assert body["error_code"] == "role_not_allowed"


def test_api_permission_error_carries_metadata() -> None:
    err = ApiPermissionError(required_roles=("admin",), actual_role="viewer")
    assert err.required_roles == ("admin",)
    assert err.actual_role == "viewer"
    assert "viewer" in str(err)
