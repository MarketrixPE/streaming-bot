"""PoC SDK Python para spinoff B2B SaaS — async-first.

Objetivo del spike:
    Demostrar la experiencia de integracion para un cliente: 3 metodos
    (sessions.open, behaviors.play_session, profiles.list) con tipos
    Pydantic v2, retries con backoff exponencial, idempotency keys
    automaticos, y validacion local de payloads. Compatible con el
    api_skeleton.py del mismo spike.

Como ejecutarlo:
    pip install "httpx[http2]==0.27.*" "pydantic==2.9.*" "tenacity==9.*"

    # En una terminal lanza el api_skeleton:
    # uvicorn spikes.year_3.api_skeleton:app --reload --port 8090

    # En otra:
    python spikes/year-3/sdk_python_poc.py

Dependencias explicitas: httpx, pydantic, tenacity.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import uuid
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

DEFAULT_BASE_URL = os.getenv("SPINOFF_BASE_URL", "http://127.0.0.1:8090")


class TargetSpec(BaseModel):
    type: Literal["track", "playlist", "artist", "album"]
    external_id: str
    min_plays: int = 1
    max_plays: int = 5


class SessionOpenRequest(BaseModel):
    geo: str
    device_class: Literal[
        "mobile_android_premium", "mobile_ios", "desktop_macos", "desktop_win"
    ]
    browser_engine: Literal["auto", "patchright", "camoufox"] = "auto"
    ttl_seconds: int = Field(1800, ge=60, le=3600)
    proxy_mode: Literal["managed", "byo", "none"] = "managed"
    labels: dict[str, str] | None = None


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


class BehaviorPlayRequest(BaseModel):
    target_dsp: Literal["spotify", "deezer", "soundcloud", "apple_music", "amazon_music"]
    targets: list[TargetSpec]
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


class SpinoffClientError(Exception):
    """Errores no-retryables (4xx)."""

    def __init__(self, status_code: int, error_code: str, message: str, request_id: str) -> None:
        super().__init__(f"[{status_code}/{error_code}] {message} (req={request_id})")
        self.status_code = status_code
        self.error_code = error_code


class SpinoffServerError(Exception):
    """Errores retryables (5xx, 429)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"[{status_code}] {message}")
        self.status_code = status_code


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (SpinoffServerError, httpx.TransportError, httpx.HTTPError))


class _Sessions:
    def __init__(self, client: "Client") -> None:
        self._client = client

    @retry(
        retry=retry_if_exception_type((SpinoffServerError, httpx.TransportError)),
        wait=wait_exponential(min=0.5, max=8),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def open(
        self, req: SessionOpenRequest, idempotency_key: str | None = None
    ) -> SessionOpenResponse:
        body = req.model_dump(exclude_none=True)
        resp = await self._client._post(
            "/v1/sessions",
            json_body=body,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )
        return SessionOpenResponse(**resp)


class _Behaviors:
    def __init__(self, client: "Client") -> None:
        self._client = client

    @retry(
        retry=retry_if_exception_type((SpinoffServerError, httpx.TransportError)),
        wait=wait_exponential(min=0.5, max=8),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def play_session(
        self, req: BehaviorPlayRequest, idempotency_key: str | None = None
    ) -> BehaviorPlayResponse:
        body = req.model_dump(exclude_none=True)
        resp = await self._client._post(
            "/v1/behaviors/play_session",
            json_body=body,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )
        return BehaviorPlayResponse(**resp)


class _Profiles:
    def __init__(self, client: "Client") -> None:
        self._client = client

    async def list(self) -> list[dict[str, Any]]:
        resp = await self._client._get("/v1/profiles")
        return resp.get("profiles", [])


class Client:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 30.0,
        http2: bool = True,
    ) -> None:
        self._api_key = api_key
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_s,
            http2=http2,
            headers={"User-Agent": "spinoff-saas-sdk-python/0.1.0"},
        )
        self.sessions = _Sessions(self)
        self.behaviors = _Behaviors(self)
        self.profiles = _Profiles(self)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "Client":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        resp = await self._http.request(method, path, json=json_body, headers=headers)
        if resp.status_code >= 500 or resp.status_code == 429:
            raise SpinoffServerError(resp.status_code, resp.text[:200])
        if resp.status_code >= 400:
            try:
                payload = resp.json()
            except Exception:
                payload = {"error_code": str(resp.status_code), "message": resp.text}
            raise SpinoffClientError(
                resp.status_code,
                str(payload.get("error_code", resp.status_code)),
                str(payload.get("message", "client error")),
                str(payload.get("request_id", "?")),
            )
        return resp.json() if resp.content else {}

    async def _get(self, path: str) -> dict[str, Any]:
        return await self._request("GET", path)

    async def _post(
        self, path: str, json_body: dict[str, Any], idempotency_key: str | None = None
    ) -> dict[str, Any]:
        return await self._request("POST", path, json_body=json_body, idempotency_key=idempotency_key)


async def _demo() -> None:
    api_key = os.getenv("SPINOFF_API_KEY", "sk_test_demo_001")
    async with Client(api_key=api_key) as client:
        profiles = await client.profiles.list()
        print(f"[sdk] profiles available: {len(profiles)}")
        for p in profiles[:3]:
            print(f"  - {p['id']} v{p['version']}  geo={p['geo']}")

        ses = await client.sessions.open(
            SessionOpenRequest(
                geo="BR-SP",
                device_class="mobile_android_premium",
                ttl_seconds=900,
            )
        )
        print(f"[sdk] session opened: {ses.session_id}")
        print(f"  ws_endpoint = {ses.ws_endpoint}")
        print(f"  expires_at  = {ses.expires_at.isoformat()}")
        print(f"  fingerprint = {ses.fingerprint_summary.model_dump()}")

        play = await client.behaviors.play_session(
            BehaviorPlayRequest(
                target_dsp="spotify",
                targets=[
                    TargetSpec(
                        type="playlist",
                        external_id="37i9dQZF1DXcBWIGoYBM5M",
                        min_plays=3,
                        max_plays=5,
                    )
                ],
                behavior_profile_id="superfan_premium_br_v3",
                geo="BR-SP",
                device_class="mobile_android_premium",
                constraints={"min_save_rate": 0.06, "max_skip_rate": 0.25},
            )
        )
        print(f"[sdk] behavior run started: {play.behavior_run_id}")
        print(f"  estimated_duration_s = {play.estimated_duration_seconds}")


if __name__ == "__main__":
    try:
        asyncio.run(_demo())
    except SpinoffClientError as e:
        print(f"[sdk] client error: {e}")
    except SpinoffServerError as e:
        print(f"[sdk] server error after retries: {e}")
    except httpx.ConnectError as e:
        print(f"[sdk] cannot connect to server: {e}. Is api_skeleton running on :8090?")
