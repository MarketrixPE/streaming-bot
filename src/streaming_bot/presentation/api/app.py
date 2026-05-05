"""Factory de la aplicacion FastAPI v1.

Entry point principal: ``create_app(settings, container)``.

Lifespan:
- Si se recibe un container precableado (tests), se reusa y la lifespan
  no construye uno nuevo.
- Si no se recibe container, la lifespan construye un ``ProductionContainer``
  desde ``Settings`` y arranca el servidor de metricas Prometheus en un
  thread separado (cuando el flag esta activado).
- En shutdown se llama a ``container.dispose()`` siempre que la lifespan
  haya construido el container.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

from streaming_bot.config import Settings
from streaming_bot.container import ProductionContainer
from streaming_bot.infrastructure.observability.metrics import start_metrics_server
from streaming_bot.presentation.api.auth import JWTAuthValidator
from streaming_bot.presentation.api.errors import register_exception_handlers
from streaming_bot.presentation.api.middleware import (
    PrometheusMiddleware,
    RateLimitMiddleware,
    RequestIdMiddleware,
    metrics_endpoint,
)
from streaming_bot.presentation.api.routers import (
    accounts,
    catalog,
    health,
    jobs,
    metrics,
    routing,
)

if TYPE_CHECKING:
    from streaming_bot.presentation.api.auth import JwksFetcher

logger = logging.getLogger("streaming_bot.api.app")


def _build_validator(
    settings: Settings,
    *,
    fetcher: JwksFetcher | None = None,
) -> JWTAuthValidator:
    api = settings.api
    return JWTAuthValidator(
        jwks_url=api.jwt_jwks_url,
        ttl_seconds=api.jwt_jwks_ttl_seconds,
        algorithms=api.jwt_algorithms,
        audience=api.jwt_audience,
        issuer=api.jwt_issuer,
        fetcher=fetcher,
    )


def create_app(
    *,
    settings: Settings | None = None,
    container: ProductionContainer | None = None,
    jwt_validator: JWTAuthValidator | None = None,
    enable_rate_limit: bool = True,
    enable_metrics_server: bool = True,
) -> FastAPI:
    """Construye una instancia FastAPI lista para servir.

    Args:
        settings: configuracion global. Si None, se carga desde env.
        container: ProductionContainer ya construido. Si None, lo crea
            la lifespan al startup. Pasalo en tests para evitar I/O.
        jwt_validator: validator pre-construido. En tests inyectar uno
            con un ``JwksFetcher`` fake. Si None se construye desde
            settings.
        enable_rate_limit: desactivable en tests para no falsear 429.
        enable_metrics_server: si False no arranca el http server de
            Prometheus (util en tests para no abrir puertos).
    """
    settings = settings or Settings()
    api_settings = settings.api
    preconfigured = container

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns_container = False
        if preconfigured is None and getattr(app.state, "container", None) is None:
            built = ProductionContainer.build(settings)
            app.state.container = built
            owns_container = True
            if enable_metrics_server and settings.observability.metrics_enabled:
                try:
                    start_metrics_server(settings.observability.metrics_port)
                except OSError as exc:
                    logger.warning(
                        "metrics_server_unavailable: %s",
                        exc,
                        extra={"port": settings.observability.metrics_port},
                    )
        try:
            yield
        finally:
            if owns_container:
                built_container = app.state.container
                await built_container.dispose()

    app = FastAPI(
        title="streaming-bot API",
        description=(
            "API REST v1 read-only para el dashboard de operacion. "
            "Auth JWT compatible con Better Auth (RS256 + JWKS)."
        ),
        version="1.0.0",
        docs_url="/docs" if api_settings.docs_enabled else None,
        redoc_url="/redoc" if api_settings.docs_enabled else None,
        openapi_url="/openapi.json" if api_settings.docs_enabled else None,
        lifespan=lifespan,
    )

    app.state.settings = settings
    if preconfigured is not None:
        app.state.container = preconfigured
    app.state.jwt_validator = jwt_validator or _build_validator(settings)

    # Middlewares: ordenados de fuera adentro (el ultimo registrado se
    # ejecuta primero al recibir el request).
    if api_settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(api_settings.allowed_origins),
            allow_credentials=True,
            allow_methods=["GET", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=[api_settings.request_id_header],
        )
    app.add_middleware(PrometheusMiddleware)
    if enable_rate_limit:
        app.add_middleware(
            RateLimitMiddleware,
            authenticated_per_minute=api_settings.rate_limit_per_minute,
            anonymous_per_minute=api_settings.anonymous_rate_limit_per_minute,
        )
    app.add_middleware(
        RequestIdMiddleware,
        header_name=api_settings.request_id_header,
    )

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(catalog.router)
    app.include_router(accounts.router)
    app.include_router(jobs.router)
    app.include_router(metrics.router)
    app.include_router(routing.router)

    @app.get(
        "/metrics",
        include_in_schema=False,
        summary="Snapshot Prometheus",
        description="Expone el formato text/plain consumido por scrapers Prometheus.",
    )
    def prometheus_snapshot() -> Response:
        return metrics_endpoint()

    return app
