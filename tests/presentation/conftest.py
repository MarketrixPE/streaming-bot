"""Fixtures compartidos para los tests de la API REST.

Filosofia:
- No tocar Postgres real. Toda la cadena container -> repos se mockea.
- Cada test override las dependencias FastAPI que necesite.
- ``api_client`` devuelve un ``httpx.AsyncClient`` listo para usar con
  ``ASGITransport`` (sin lifespan, evita arranque del container real).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from streaming_bot.config import Settings
from streaming_bot.presentation.api.app import create_app
from streaming_bot.presentation.api.auth import AuthenticatedUser, JWTAuthValidator
from streaming_bot.presentation.api.dependencies import (
    get_account_repository,
    get_api_dependencies,
    get_artist_repository,
    get_container,
    get_current_user,
    get_jwt_validator,
    get_label_repository,
    get_session,
    get_session_record_repository,
    get_song_repository,
    get_stream_history_repository,
)


def _make_user(role: str = "admin") -> AuthenticatedUser:
    return AuthenticatedUser(
        id=f"user-{role}",
        role=role,
        email=f"{role}@example.com",
        raw_claims={"sub": f"user-{role}", "role": role},
    )


@pytest.fixture
def fake_validator() -> JWTAuthValidator:
    """Validator dummy con fetcher fake; nunca se llama directamente."""

    class _NullFetcher:
        async def fetch(self, jwks_url: str) -> dict[str, Any]:
            return {"keys": []}

    return JWTAuthValidator(jwks_url="http://test/jwks", fetcher=_NullFetcher())


@pytest.fixture
def fake_settings(tmp_path) -> Settings:  # type: ignore[no-untyped-def]
    """Settings minimales para los tests (sqlite in-memory)."""
    return Settings(
        api={  # type: ignore[arg-type]
            "host": "127.0.0.1",
            "port": 8000,
            "jwt_jwks_url": "http://test/jwks",
            "rate_limit_per_minute": 1000,
            "anonymous_rate_limit_per_minute": 1000,
        },
        database={"url": "sqlite+aiosqlite:///:memory:"},  # type: ignore[arg-type]
        observability={"metrics_enabled": False},  # type: ignore[arg-type]
        storage={"sessions_dir": str(tmp_path / "sessions")},  # type: ignore[arg-type]
    )


def build_app_with_overrides(
    *,
    settings: Settings,
    validator: JWTAuthValidator,
    user: AuthenticatedUser | None = None,
    container: Any | None = None,
    account_repo: Any | None = None,
    artist_repo: Any | None = None,
    label_repo: Any | None = None,
    song_repo: Any | None = None,
    session_record_repo: Any | None = None,
    stream_history_repo: Any | None = None,
    session: Any | None = None,
) -> Any:
    """Construye la app con overrides aplicados."""
    if container is None:
        container = MagicMock()
        container.anomaly_predictor = None
        container.track_health_repository = None
    app = create_app(
        settings=settings,
        container=container,
        jwt_validator=validator,
        enable_rate_limit=False,
        enable_metrics_server=False,
    )

    fake_session_obj = session if session is not None else AsyncMock()

    async def _fake_session() -> AsyncIterator[Any]:
        yield fake_session_obj

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_container] = lambda: container
    app.dependency_overrides[get_jwt_validator] = lambda: validator
    app.dependency_overrides[get_api_dependencies] = lambda: MagicMock(container=container)

    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    if account_repo is not None:
        app.dependency_overrides[get_account_repository] = lambda: account_repo
    if artist_repo is not None:
        app.dependency_overrides[get_artist_repository] = lambda: artist_repo
    if label_repo is not None:
        app.dependency_overrides[get_label_repository] = lambda: label_repo
    if song_repo is not None:
        app.dependency_overrides[get_song_repository] = lambda: song_repo
    if session_record_repo is not None:
        app.dependency_overrides[get_session_record_repository] = lambda: session_record_repo
    if stream_history_repo is not None:
        app.dependency_overrides[get_stream_history_repository] = lambda: stream_history_repo
    return app


@pytest.fixture
def make_user() -> Any:
    """Factory de AuthenticatedUser para los tests."""
    return _make_user


@pytest.fixture
async def api_client(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
) -> AsyncIterator[AsyncClient]:
    """Cliente con admin user por defecto y stubs neutros."""
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=_make_user("admin"),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
