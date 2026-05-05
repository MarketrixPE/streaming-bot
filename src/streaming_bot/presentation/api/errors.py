"""Manejadores globales de excepciones para la API REST.

Mapeo:
- ``DomainError`` y subclases -> 400 (excepto ``AuthenticationError``).
- ``ApiAuthenticationError`` -> 401.
- ``ApiPermissionError`` / ``PermissionError`` builtin -> 403.
- ``NotFoundError`` -> 404.
- ``RequestValidationError`` (Pydantic) -> 422 con response uniform.
- Cualquier otra excepcion -> 500 con tracking del request id.

Todos los errores se serializan como ``ErrorResponse`` para que los
clientes puedan parsear de forma uniforme.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from streaming_bot.domain.exceptions import (
    AuthenticationError as DomainAuthenticationError,
)
from streaming_bot.domain.exceptions import (
    DomainError,
)
from streaming_bot.presentation.api.auth import (
    ApiAuthenticationError,
    ApiPermissionError,
)
from streaming_bot.presentation.api.schemas import ErrorResponse

if TYPE_CHECKING:
    from fastapi import FastAPI, Request


logger = logging.getLogger("streaming_bot.api.errors")


class NotFoundError(Exception):
    """Recurso pedido por id que no existe (404 con cuerpo uniforme)."""

    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(f"{resource}_not_found: {identifier}")
        self.resource = resource
        self.identifier = identifier


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _payload(error_code: str, message: str, request_id: str) -> dict[str, str]:
    return ErrorResponse(
        error_code=error_code,
        message=message,
        request_id=request_id,
    ).model_dump()


def _add_handler(app: FastAPI, exc_cls: type, handler: object) -> None:
    """Workaround tipado: FastAPI.add_exception_handler usa Callable poco preciso."""
    app.add_exception_handler(exc_cls, handler)  # type: ignore[arg-type]


def register_exception_handlers(app: FastAPI) -> None:
    """Registra los handlers globales de la API en el ``app`` recibido."""

    async def _handle_not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=_payload(
                error_code=f"{exc.resource}_not_found",
                message=str(exc),
                request_id=_request_id(request),
            ),
        )

    async def _handle_api_auth(
        request: Request,
        exc: ApiAuthenticationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content=_payload(
                error_code=exc.code,
                message=str(exc),
                request_id=_request_id(request),
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def _handle_api_permission(
        request: Request,
        exc: ApiPermissionError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content=_payload(
                error_code="role_not_allowed",
                message=str(exc),
                request_id=_request_id(request),
            ),
        )

    async def _handle_python_permission(
        request: Request,
        exc: PermissionError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content=_payload(
                error_code="permission_denied",
                message=str(exc) or "permission_denied",
                request_id=_request_id(request),
            ),
        )

    async def _handle_domain_auth(
        request: Request,
        exc: DomainAuthenticationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content=_payload(
                error_code="authentication_failed",
                message=str(exc),
                request_id=_request_id(request),
            ),
        )

    async def _handle_domain(
        request: Request,
        exc: DomainError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=_payload(
                error_code="domain_error",
                message=str(exc),
                request_id=_request_id(request),
            ),
        )

    async def _handle_validation(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_payload(
                error_code="validation_error",
                message=str(jsonable_encoder(exc.errors())),
                request_id=_request_id(request),
            ),
        )

    async def _handle_http(request: Request, exc: HTTPException) -> JSONResponse:
        # HTTPException levantadas adrede en handlers (ej. 404 explicito)
        # se serializan con el mismo formato uniforme.
        detail = exc.detail if isinstance(exc.detail, str) else "http_error"
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(
                error_code=f"http_{exc.status_code}",
                message=str(detail),
                request_id=_request_id(request),
            ),
            headers=exc.headers,
        )

    async def _handle_unexpected(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        request_id = _request_id(request)
        logger.exception(
            "api.unhandled_exception",
            extra={"request_id": request_id, "path": str(request.url.path)},
        )
        return JSONResponse(
            status_code=500,
            content=_payload(
                error_code="internal_server_error",
                message=f"unexpected_error:{type(exc).__name__}",
                request_id=request_id,
            ),
        )

    _add_handler(app, NotFoundError, _handle_not_found)
    _add_handler(app, ApiAuthenticationError, _handle_api_auth)
    _add_handler(app, ApiPermissionError, _handle_api_permission)
    _add_handler(app, PermissionError, _handle_python_permission)
    _add_handler(app, DomainAuthenticationError, _handle_domain_auth)
    _add_handler(app, DomainError, _handle_domain)
    _add_handler(app, RequestValidationError, _handle_validation)
    _add_handler(app, HTTPException, _handle_http)
    _add_handler(app, Exception, _handle_unexpected)
