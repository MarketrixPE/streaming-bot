"""Dependencias FastAPI compartidas por todos los routers.

Capas de DI:
1. ``get_container`` lee ``request.app.state.container`` (poblado en
   ``create_app`` o por la lifespan en runtime).
2. ``get_api_dependencies`` envuelve el container en ``ApiDependencies``.
3. ``get_session`` abre una sesion transaccional unica por request.
4. Repos (``get_account_repository``, etc.) se construyen sobre la
   sesion para que los handlers reciban puertos de dominio limpios.
5. ``get_jwt_validator`` lee el validator instanciado en ``create_app``.
6. ``get_current_user`` extrae el Bearer token y valida.
7. ``require_role(...)`` factoriza el RBAC.

Todas las dependencias son async-friendly y testables: en tests basta
con ``app.dependency_overrides[get_current_user] = lambda: User(...)``
para inyectar un usuario fake sin tocar JWT.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.container import ApiDependencies, ProductionContainer
from streaming_bot.domain.ports import (
    IAccountRepository,
    IArtistRepository,
    ILabelRepository,
    ISessionRecordRepository,
    ISongRepository,
    IStreamHistoryRepository,
)
from streaming_bot.presentation.api.auth import (
    ApiAuthenticationError,
    ApiPermissionError,
    AuthenticatedUser,
    JWTAuthValidator,
)


def get_container(request: Request) -> ProductionContainer:
    """Recupera el ProductionContainer del estado de la app."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise ApiAuthenticationError(
            "container_unavailable",
            "container no inicializado en app.state",
        )
    if not isinstance(container, ProductionContainer):  # pragma: no cover - defensiva
        raise ApiAuthenticationError(
            "container_type_invalid",
            "app.state.container debe ser ProductionContainer",
        )
    return container


def get_api_dependencies(
    container: Annotated[ProductionContainer, Depends(get_container)],
) -> ApiDependencies:
    """Wrapper inyectable con factories para los routers."""
    cached = getattr(container, "_api_deps_cache", None)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    deps = container.make_api_dependencies()
    container._api_deps_cache = deps  # type: ignore[attr-defined]
    return deps


async def get_session(
    deps: Annotated[ApiDependencies, Depends(get_api_dependencies)],
) -> AsyncIterator[AsyncSession]:
    """Sesion transaccional unica por request (commit/rollback automatico)."""
    async with deps.session_scope() as session:
        yield session


# ---------------------------------------------------------------------------
# Repos
# ---------------------------------------------------------------------------
def get_account_repository(
    deps: Annotated[ApiDependencies, Depends(get_api_dependencies)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IAccountRepository:
    return deps.make_account_repository(session)


def get_artist_repository(
    deps: Annotated[ApiDependencies, Depends(get_api_dependencies)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IArtistRepository:
    return deps.make_artist_repository(session)


def get_label_repository(
    deps: Annotated[ApiDependencies, Depends(get_api_dependencies)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ILabelRepository:
    return deps.make_label_repository(session)


def get_song_repository(
    deps: Annotated[ApiDependencies, Depends(get_api_dependencies)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ISongRepository:
    return deps.make_song_repository(session)


def get_session_record_repository(
    deps: Annotated[ApiDependencies, Depends(get_api_dependencies)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ISessionRecordRepository:
    repo: ISessionRecordRepository = deps.make_session_record_repository(session)
    return repo


def get_stream_history_repository(
    deps: Annotated[ApiDependencies, Depends(get_api_dependencies)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IStreamHistoryRepository:
    repo: IStreamHistoryRepository = deps.make_stream_history_repository(session)
    return repo


# ---------------------------------------------------------------------------
# Auth + RBAC
# ---------------------------------------------------------------------------
def get_jwt_validator(request: Request) -> JWTAuthValidator:
    validator = getattr(request.app.state, "jwt_validator", None)
    if validator is None:
        raise ApiAuthenticationError(
            "jwt_validator_unavailable",
            "JWTAuthValidator no inicializado en app.state",
        )
    if not isinstance(validator, JWTAuthValidator):  # pragma: no cover - defensiva
        raise ApiAuthenticationError(
            "jwt_validator_type_invalid",
            "app.state.jwt_validator debe ser JWTAuthValidator",
        )
    return validator


async def get_current_user(
    request: Request,
    validator: Annotated[JWTAuthValidator, Depends(get_jwt_validator)],
) -> AuthenticatedUser:
    """Valida el Bearer token y devuelve el usuario autenticado."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise ApiAuthenticationError(
            "missing_bearer_token",
            "header Authorization Bearer requerido",
        )
    token = auth_header.split(" ", 1)[1].strip()
    user = await validator.validate(token)
    request.state.user = user
    return user


RoleDependency = Callable[
    [AuthenticatedUser],
    Coroutine[Any, Any, AuthenticatedUser],
]


def require_role(*allowed_roles: str) -> RoleDependency:
    """Factory de dependencia RBAC.

    Uso:
        @router.get(..., dependencies=[Depends(require_role("admin"))])
        async def handler(...): ...

    El primer rol coincidente concede acceso. Roles canonicos: viewer,
    operator, admin. Lista vacia => sin restriccion (no recomendable).
    """
    if not allowed_roles:
        raise ValueError("require_role necesita al menos un rol")
    normalized = tuple(role.lower() for role in allowed_roles)

    async def _dep(
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        if user.role.lower() not in normalized:
            raise ApiPermissionError(required_roles=normalized, actual_role=user.role)
        return user

    return _dep
