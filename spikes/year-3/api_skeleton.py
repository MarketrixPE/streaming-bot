"""PoC API skeleton del spinoff B2B SaaS — FastAPI minimo.

Objetivo del spike:
    Esqueleto FastAPI ejecutable de 3 endpoints (POST /v1/sessions,
    POST /v1/behaviors/play_session, GET /v1/profiles) con autenticacion
    por api key, validacion Pydantic, idempotency keys, rate limiting in-memory,
    y stubs que devuelven respuestas conformes al spec en
    docs/strategy/year-3/02-product-spec.md.

Como ejecutarlo:
    pip install "fastapi[standard]==0.115.*" "uvicorn[standard]==0.32.*" \
                "pydantic==2.9.*" "redis==5.*"
    uvicorn spikes.year_3.api_skeleton:app --reload --port 8090

    # Probar:
    # curl -H "Authorization: Bearer sk_test_demo_001" \
    #      http://127.0.0.1:8090/v1/profiles
    # curl -X POST http://127.0.0.1:8090/v1/sessions \
    #      -H "Authorization: Bearer sk_test_demo_001" \
    #      -H "Idempotency-Key: 11111111-1111-1111-1111-111111111111" \
    #      -H "Content-Type: application/json" \
    #      -d '{"geo":"BR-SP","device_class":"mobile_android_premium",
    #            "browser_engine":"auto","ttl_seconds":1800,
    #            "proxy_mode":"managed"}'

Dependencias explicitas: fastapi, uvicorn, pydantic. Redis es opcional;
el spike usa un fallback in-memory si REDIS_URL no esta seteado.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import secrets
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Deque, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

API_VERSION = "v1"
SERVICE_NAME = "spinoff-saas-skeleton"

DEMO_API_KEYS: dict[str, dict[str, Any]] = {
    "sk_test_demo_001": {"tenant_id": "tnt_demo_001", "tier": "standard", "credits_cents": 50_000},
    "sk_test_demo_002": {"tenant_id": "tnt_demo_002", "tier": "pro", "credits_cents": 250_000},
}

PROFILES_CATALOG: list[dict[str, Any]] = [
    {
        "id": "superfan_premium_br_v3",
        "description": "Super-fan premium BR — sesiones largas 5-15 min, repeat behavior, save rate 5-12%, queue rate 3-5%, premium listener.",
        "geo": ["BR-SP", "BR-RJ", "BR-MG"],
        "device_classes": ["mobile_android_premium", "mobile_ios"],
        "params": {
            "min_save_rate": 0.05,
            "max_skip_rate": 0.30,
            "intensity_levels": ["low", "medium", "high"],
        },
        "version": "3.1.0",
        "trained_on_samples": 184_523,
        "compatibility": ["spotify", "deezer"],
    },
    {
        "id": "casual_premium_us_v2",
        "description": "Casual premium US — sesiones cortas 2-6 min, low save rate.",
        "geo": ["US"],
        "device_classes": ["desktop_macos", "desktop_win", "mobile_ios"],
        "params": {"min_save_rate": 0.02, "max_skip_rate": 0.45},
        "version": "2.4.1",
        "trained_on_samples": 412_004,
        "compatibility": ["spotify", "apple_music", "amazon_music"],
    },
]


class TenantState:
    """Estado in-memory para el spike (en produccion vive en Postgres + Redis)."""

    def __init__(self) -> None:
        self.idempotency_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.rate_buckets: dict[str, Deque[float]] = defaultdict(deque)
        self.credits_cents: dict[str, int] = {
            v["tenant_id"]: int(v["credits_cents"]) for v in DEMO_API_KEYS.values()
        }
        self.session_audit: list[dict[str, Any]] = []


STATE = TenantState()


class Tenant(BaseModel):
    api_key_hash: str
    tenant_id: str
    tier: Literal["standard", "pro", "volume"]
    credits_cents: int


def _hash_api_key(api_key: str) -> str:
    return hashlib.blake2b(api_key.encode(), digest_size=16, key=b"spinoff-skel").hexdigest()


async def authenticate(authorization: str | None = Header(default=None)) -> Tenant:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer api key")
    api_key = authorization.removeprefix("Bearer ").strip()
    record = DEMO_API_KEYS.get(api_key)
    if record is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")
    return Tenant(
        api_key_hash=_hash_api_key(api_key),
        tenant_id=record["tenant_id"],
        tier=record["tier"],
        credits_cents=STATE.credits_cents.get(record["tenant_id"], 0),
    )


def rate_limit(tenant: Tenant, max_per_window: int = 60, window_s: float = 1.0) -> None:
    now = time.monotonic()
    bucket = STATE.rate_buckets[tenant.tenant_id]
    while bucket and now - bucket[0] > window_s:
        bucket.popleft()
    if len(bucket) >= max_per_window:
        retry_after = int(window_s - (now - bucket[0]) + 1)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    bucket.append(now)


def consume_credits(tenant: Tenant, cents: int, reason: str) -> int:
    cur = STATE.credits_cents.get(tenant.tenant_id, 0)
    if cur < cents:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"insufficient credits: need {cents}, have {cur}",
        )
    STATE.credits_cents[tenant.tenant_id] = cur - cents
    STATE.session_audit.append(
        {"tenant_id": tenant.tenant_id, "reason": reason, "delta_cents": -cents, "ts": time.time()}
    )
    return STATE.credits_cents[tenant.tenant_id]


class SessionOpenRequest(BaseModel):
    geo: str = Field(..., min_length=2, max_length=12, examples=["BR-SP"])
    device_class: Literal[
        "mobile_android_premium", "mobile_ios", "desktop_macos", "desktop_win"
    ]
    browser_engine: Literal["auto", "patchright", "camoufox"] = "auto"
    ttl_seconds: int = Field(1800, ge=60, le=3600)
    proxy_mode: Literal["managed", "byo", "none"] = "managed"
    labels: dict[str, str] | None = None

    @field_validator("geo")
    @classmethod
    def normalize_geo(cls, v: str) -> str:
        return v.strip().upper()


class FingerprintSummary(BaseModel):
    ua_family: str
    locale: str
    timezone: str
    ja4_hash: str


class BillingMeta(BaseModel):
    mode: Literal["session_basic", "session_rich"]
    credits_held_cents: int


class SessionOpenResponse(BaseModel):
    session_id: str
    ws_endpoint: str
    expires_at: dt.datetime
    fingerprint_summary: FingerprintSummary
    billing: BillingMeta


class TargetSpec(BaseModel):
    type: Literal["track", "playlist", "artist", "album"]
    external_id: str = Field(..., min_length=4)
    min_plays: int = Field(1, ge=1, le=20)
    max_plays: int = Field(5, ge=1, le=20)


class BehaviorPlayRequest(BaseModel):
    target_dsp: Literal["spotify", "deezer", "soundcloud", "apple_music", "amazon_music"]
    targets: list[TargetSpec] = Field(..., min_length=1, max_length=8)
    behavior_profile_id: str
    geo: str
    device_class: Literal[
        "mobile_android_premium", "mobile_ios", "desktop_macos", "desktop_win"
    ]
    constraints: dict[str, Any] | None = None
    callback_webhook_url: str | None = None


class BehaviorPlayResponse(BaseModel):
    session_id: str
    behavior_run_id: str
    status: Literal["running", "queued"]
    estimated_duration_seconds: int
    billing: BillingMeta


class ProfilesResponse(BaseModel):
    profiles: list[dict[str, Any]]
    total: int


def _idempotency_lookup(tenant_id: str, key: str) -> dict[str, Any] | None:
    return STATE.idempotency_cache.get((tenant_id, key))


def _idempotency_store(tenant_id: str, key: str, value: dict[str, Any]) -> None:
    STATE.idempotency_cache[(tenant_id, key)] = value


app = FastAPI(title=SERVICE_NAME, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=False,
)


@app.get("/healthz", tags=["meta"])
async def healthz() -> dict[str, Any]:
    return {"ok": True, "service": SERVICE_NAME, "ts": time.time()}


@app.get(f"/{API_VERSION}/profiles", response_model=ProfilesResponse, tags=["profiles"])
async def list_profiles(tenant: Tenant = Depends(authenticate)) -> ProfilesResponse:
    rate_limit(tenant, max_per_window=120)
    return ProfilesResponse(profiles=PROFILES_CATALOG, total=len(PROFILES_CATALOG))


@app.post(
    f"/{API_VERSION}/sessions",
    response_model=SessionOpenResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["sessions"],
)
async def open_session(
    body: SessionOpenRequest,
    request: Request,
    tenant: Tenant = Depends(authenticate),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SessionOpenResponse:
    rate_limit(tenant)

    if idempotency_key:
        cached = _idempotency_lookup(tenant.tenant_id, idempotency_key)
        if cached is not None:
            return SessionOpenResponse(**cached)

    consume_credits(tenant, cents=5, reason="session_basic_hold")

    session_id = "ses_" + uuid.uuid4().hex[:16]
    ws = (
        f"wss://edge-fi-1.api.spinoff-saas.local/{API_VERSION}/sessions/"
        f"{session_id}/ws?token={secrets.token_urlsafe(20)}"
    )
    expires = dt.datetime.now(tz=dt.UTC) + dt.timedelta(seconds=body.ttl_seconds)

    fp = FingerprintSummary(
        ua_family="Chrome 137 / Android 16",
        locale=("pt-BR" if body.geo.startswith("BR") else "en-US"),
        timezone=("America/Sao_Paulo" if body.geo.startswith("BR") else "America/New_York"),
        ja4_hash="ja4_" + secrets.token_hex(8),
    )

    response = SessionOpenResponse(
        session_id=session_id,
        ws_endpoint=ws,
        expires_at=expires,
        fingerprint_summary=fp,
        billing=BillingMeta(mode="session_basic", credits_held_cents=5),
    )
    if idempotency_key:
        _idempotency_store(tenant.tenant_id, idempotency_key, response.model_dump(mode="json"))
    return response


@app.post(
    f"/{API_VERSION}/behaviors/play_session",
    response_model=BehaviorPlayResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["behaviors"],
)
async def play_session(
    body: BehaviorPlayRequest,
    tenant: Tenant = Depends(authenticate),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> BehaviorPlayResponse:
    rate_limit(tenant)
    if not any(p["id"] == body.behavior_profile_id for p in PROFILES_CATALOG):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown behavior_profile_id: {body.behavior_profile_id}",
        )

    if idempotency_key:
        cached = _idempotency_lookup(tenant.tenant_id, idempotency_key)
        if cached is not None:
            return BehaviorPlayResponse(**cached)

    consume_credits(tenant, cents=20, reason="session_rich_hold")

    session_id = "ses_" + uuid.uuid4().hex[:16]
    behavior_run_id = "br_" + uuid.uuid4().hex[:16]
    estimated = max(180, sum(t.max_plays * 90 for t in body.targets))

    response = BehaviorPlayResponse(
        session_id=session_id,
        behavior_run_id=behavior_run_id,
        status="running",
        estimated_duration_seconds=estimated,
        billing=BillingMeta(mode="session_rich", credits_held_cents=20),
    )
    if idempotency_key:
        _idempotency_store(tenant.tenant_id, idempotency_key, response.model_dump(mode="json"))
    return response


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> Any:
    from fastapi.responses import JSONResponse

    payload = {
        "error_code": str(exc.status_code),
        "message": exc.detail if isinstance(exc.detail, str) else "error",
        "request_id": request.headers.get("X-Request-Id", uuid.uuid4().hex),
    }
    headers = exc.headers if exc.headers else {}
    return JSONResponse(status_code=exc.status_code, content=payload, headers=headers)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api_skeleton:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8090")),
        reload=True,
    )
