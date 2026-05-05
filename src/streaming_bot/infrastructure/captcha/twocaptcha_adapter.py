"""TwoCaptchaAdapter: ICaptchaSolver para 2Captcha (https://2captcha.com).

Docs: https://2captcha.com/api-docs

Flujo classic-API:
1. POST a `https://2captcha.com/in.php` con
   `key`, `method` y los parametros del captcha. Por defecto el body
   responde texto plano `OK|<id>`. Si pedimos `json=1` retorna
   `{ status: 1, request: "<id>" }`.
2. Polling cada `poll_interval_seconds` a
   `https://2captcha.com/res.php?key=KEY&action=get&id=<id>` (json=1)
   hasta `status=1`. Mientras tanto el cuerpo es `CAPCHA_NOT_READY`.

Tasks soportadas:
- userrecaptcha     -> reCAPTCHA v2 (proxyless si no se manda proxy)
- userrecaptcha v3  -> reCAPTCHA v3 (`version=v3`, `action`, `min_score`)
- hcaptcha          -> hCaptcha
- turnstile         -> Cloudflare Turnstile
- base64            -> CAPTCHA de imagen distorsionada

Costes aproximados Q4 2025 (~10% mas caros que CapSolver):
- reCAPTCHA v2: USD 0.88 / 1k => 0.088 cents/solve
- reCAPTCHA v3: USD 1.32 / 1k => 0.132 cents/solve
- hCaptcha:    USD 1.10 / 1k => 0.110 cents/solve
- Turnstile:   USD 0.88 / 1k => 0.088 cents/solve
- Imagen:      USD 0.50 / 1k => 0.050 cents/solve
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from streaming_bot.domain.ports.captcha_solver import (
    CaptchaSolverError,
    ICaptchaSolver,
)

DEFAULT_BASE_URL = "https://2captcha.com"


class TwoCaptchaAdapter(ICaptchaSolver):
    """Adapter HTTP para 2Captcha (in.php / res.php classic API)."""

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_BASE_URL,
        poll_interval_seconds: float = 5.0,
        solve_timeout_seconds: float = 180.0,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._poll_interval = poll_interval_seconds
        self._solve_timeout = solve_timeout_seconds
        self._request_timeout = request_timeout_seconds
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=request_timeout_seconds)
        self._log = structlog.get_logger("twocaptcha_adapter")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def solve_recaptcha_v2(self, *, site_key: str, page_url: str) -> str:
        params = {
            "method": "userrecaptcha",
            "googlekey": site_key,
            "pageurl": page_url,
        }
        return await self._submit_and_poll(params)

    async def solve_recaptcha_v3(
        self,
        *,
        site_key: str,
        page_url: str,
        action: str,
        min_score: float,
    ) -> str:
        params = {
            "method": "userrecaptcha",
            "version": "v3",
            "googlekey": site_key,
            "pageurl": page_url,
            "action": action,
            "min_score": str(min_score),
        }
        return await self._submit_and_poll(params)

    async def solve_hcaptcha(self, *, site_key: str, page_url: str) -> str:
        params = {
            "method": "hcaptcha",
            "sitekey": site_key,
            "pageurl": page_url,
        }
        return await self._submit_and_poll(params)

    async def solve_cloudflare_turnstile(self, *, site_key: str, page_url: str) -> str:
        params = {
            "method": "turnstile",
            "sitekey": site_key,
            "pageurl": page_url,
        }
        return await self._submit_and_poll(params)

    async def solve_image_text(self, *, image_b64: str, hint: str) -> str:
        params: dict[str, str] = {
            "method": "base64",
            "body": image_b64,
        }
        if hint:
            params["textinstructions"] = hint
        return await self._submit_and_poll(params)

    async def _submit_and_poll(self, params: dict[str, str]) -> str:
        if not self._api_key:
            raise CaptchaSolverError("twocaptcha: api_key vacia")

        captcha_id = await self._submit(params)
        return await self._poll(captcha_id)

    async def _submit(self, params: dict[str, str]) -> str:
        body = {"key": self._api_key, "json": "1", **params}
        url = f"{self._base_url}/in.php"
        try:
            response = await self._http.post(
                url,
                data=body,
                timeout=self._request_timeout,
            )
        except httpx.HTTPError as exc:
            raise CaptchaSolverError(f"twocaptcha in.php request fallo: {exc}") from exc

        if response.status_code >= 400:
            raise CaptchaSolverError(
                f"twocaptcha in.php status={response.status_code} body={response.text[:200]}",
            )

        data: dict[str, Any] = self._parse_json_response(response, action="in.php")
        if data.get("status") != 1:
            raise CaptchaSolverError(
                f"twocaptcha in.php error: {data.get('request') or data.get('error_text')}",
            )
        captcha_id = data.get("request")
        if not isinstance(captcha_id, str) or not captcha_id:
            raise CaptchaSolverError(f"twocaptcha in.php sin id: {data}")
        return captcha_id

    async def _poll(self, captcha_id: str) -> str:
        url = f"{self._base_url}/res.php"
        params = {
            "key": self._api_key,
            "action": "get",
            "id": captcha_id,
            "json": "1",
        }
        deadline = asyncio.get_event_loop().time() + self._solve_timeout

        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(self._poll_interval)
            try:
                response = await self._http.get(
                    url,
                    params=params,
                    timeout=self._request_timeout,
                )
            except httpx.HTTPError as exc:
                self._log.warning(
                    "twocaptcha.poll_request_failed",
                    captcha_id=captcha_id,
                    error=str(exc),
                )
                continue

            if response.status_code >= 400:
                self._log.warning(
                    "twocaptcha.poll_status_error",
                    captcha_id=captcha_id,
                    status=response.status_code,
                )
                continue

            data: dict[str, Any] = self._parse_json_response(response, action="res.php")
            request_value = data.get("request")
            if data.get("status") == 1:
                if not isinstance(request_value, str) or not request_value:
                    raise CaptchaSolverError(
                        f"twocaptcha solucion vacia: {data}",
                    )
                return request_value
            if request_value == "CAPCHA_NOT_READY":
                continue
            raise CaptchaSolverError(
                f"twocaptcha res.php error: {request_value or data.get('error_text')}",
            )

        raise CaptchaSolverError(
            f"twocaptcha timeout esperando solucion id={captcha_id} "
            f"tras {self._solve_timeout}s",
        )

    @staticmethod
    def _parse_json_response(response: httpx.Response, *, action: str) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise CaptchaSolverError(
                f"twocaptcha {action} respuesta no-JSON: {response.text[:200]}",
            ) from exc
        if not isinstance(data, dict):
            raise CaptchaSolverError(
                f"twocaptcha {action} JSON inesperado: {data!r}",
            )
        return data
