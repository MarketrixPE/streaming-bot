"""Middlewares HTTP de la API: request id, rate limit y prometheus.

- ``RequestIdMiddleware``: garantiza que cada request lleve un UUID4 en
  ``request.state.request_id`` y en el header de respuesta. Acepta el
  request id propagado por el cliente (header configurable) para
  correlacion con el dashboard Next.js.
- ``RateLimitMiddleware``: token-bucket en memoria por user_id (cuando
  el JWT incluye sub) o por IP cliente como fallback. Default 120 req/min
  para autenticados y 30 req/min para anonimos. Devuelve 429 con
  ``ErrorResponse`` uniforme.
- ``PrometheusMiddleware``: incrementa contadores de requests y observa
  duracion por (path, method, status). Histograma con buckets sub-segundo.

Decisiones:
- El rate limit identifica al usuario decodificando el JWT SIN verificar
  firma (solo para extraer ``sub``). La validacion fuerte ocurre en la
  dependencia ``get_current_user``. Esto evita doble decode pesado y
  permite rate-limit incluso si el token esta expirado.
- Token bucket en memoria: aceptable porque el deployment objetivo
  corre en un solo nodo. Si en el futuro se levantan multiples replicas
  detras de un LB, sustituir backend por Redis (slowapi soporta esto
  out-of-the-box; lo cableamos en otra iteracion).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from jose import jwt
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.types import ASGIApp

from streaming_bot.presentation.api.schemas import ErrorResponse

logger = logging.getLogger("streaming_bot.api.middleware")


# ---------------------------------------------------------------------------
# Request id
# ---------------------------------------------------------------------------
class RequestIdMiddleware(BaseHTTPMiddleware):
    """Inyecta un request id por request y lo expone en el header de respuesta."""

    def __init__(self, app: ASGIApp, *, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self._header_name = header_name

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(self._header_name)
        request_id = incoming or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[self._header_name] = request_id
        return response


# ---------------------------------------------------------------------------
# Rate limit (token bucket en memoria)
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class _Bucket:
    tokens: float
    last_refill: float
    capacity: float
    refill_per_second: float

    def consume(self, now: float, *, amount: float = 1.0) -> bool:
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(
            self.capacity,
            self.tokens + elapsed * self.refill_per_second,
        )
        self.last_refill = now
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False


def _decode_unverified_sub(token: str) -> str | None:
    """Lee el claim ``sub`` sin verificar firma (solo para clave de bucket)."""
    try:
        unverified = jwt.get_unverified_claims(token)
    except Exception:
        return None
    sub = unverified.get("sub")
    return str(sub) if sub else None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket por identidad (user_id desde JWT o IP)."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        authenticated_per_minute: int = 120,
        anonymous_per_minute: int = 30,
        skip_paths: tuple[str, ...] = (
            "/health",
            "/readyz",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/redoc",
        ),
    ) -> None:
        super().__init__(app)
        if authenticated_per_minute < 1:
            raise ValueError("authenticated_per_minute debe ser >= 1")
        if anonymous_per_minute < 1:
            raise ValueError("anonymous_per_minute debe ser >= 1")
        self._auth_capacity = float(authenticated_per_minute)
        self._auth_refill = self._auth_capacity / 60.0
        self._anon_capacity = float(anonymous_per_minute)
        self._anon_refill = self._anon_capacity / 60.0
        self._skip_paths = set(skip_paths)
        self._buckets: dict[str, _Bucket] = {}
        self._lock = asyncio.Lock()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in self._skip_paths:
            return await call_next(request)

        identity, capacity, refill = self._identify(request)
        async with self._lock:
            bucket = self._buckets.get(identity)
            now = time.monotonic()
            if bucket is None:
                bucket = _Bucket(
                    tokens=capacity,
                    last_refill=now,
                    capacity=capacity,
                    refill_per_second=refill,
                )
                self._buckets[identity] = bucket
            allowed = bucket.consume(now)

        if not allowed:
            request_id = str(getattr(request.state, "request_id", "unknown"))
            payload = ErrorResponse(
                error_code="rate_limited",
                message=f"rate_limit_exceeded:{capacity:.0f}_per_minute",
                request_id=request_id,
            ).model_dump()
            return JSONResponse(
                status_code=429,
                content=payload,
                headers={"Retry-After": "60"},
            )
        return await call_next(request)

    def _identify(self, request: Request) -> tuple[str, float, float]:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
            sub = _decode_unverified_sub(token)
            if sub:
                return f"user:{sub}", self._auth_capacity, self._auth_refill
        client = request.client
        ip = client.host if client else "unknown"
        return f"ip:{ip}", self._anon_capacity, self._anon_refill


# ---------------------------------------------------------------------------
# Prometheus
# ---------------------------------------------------------------------------
_API_REQUESTS_TOTAL = Counter(
    "streaming_bot_api_requests_total",
    "Total de requests HTTP recibidas por la API",
    labelnames=("method", "path", "status"),
)

_API_REQUEST_DURATION = Histogram(
    "streaming_bot_api_request_duration_seconds",
    "Duracion request HTTP",
    labelnames=("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Cuenta requests y mide duracion por route template (no por path raw)."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        method = request.method
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            elapsed = time.perf_counter() - start
            path_label = self._path_template(request)
            _API_REQUEST_DURATION.labels(method=method, path=path_label).observe(elapsed)
            _API_REQUESTS_TOTAL.labels(method=method, path=path_label, status="500").inc()
            raise
        else:
            elapsed = time.perf_counter() - start
            path_label = self._path_template(request)
            _API_REQUEST_DURATION.labels(method=method, path=path_label).observe(elapsed)
            _API_REQUESTS_TOTAL.labels(
                method=method,
                path=path_label,
                status=str(status),
            ).inc()
            return response

    @staticmethod
    def _path_template(request: Request) -> str:
        route = request.scope.get("route")
        if route is not None and getattr(route, "path", None):
            return str(route.path)
        return request.url.path


def metrics_endpoint() -> Response:
    """Devuelve el snapshot text/plain de prometheus_client."""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
