"""CapSolverAdapter: ICaptchaSolver implementado sobre el API HTTP de CapSolver.

Docs: https://docs.capsolver.com/

Flujo:
1. POST `https://api.capsolver.com/createTask` con `{ clientKey, task }`.
   Respuesta: `{ errorId, taskId }`. Si `errorId != 0` => fallo.
2. Polling cada `poll_interval_seconds` a `getTaskResult` con
   `{ clientKey, taskId }`. Respuesta `{ status: "ready", solution: {...} }`
   o `status: "processing"`.
3. Solucion segun task type:
   - ReCaptchaV2TaskProxyLess / ReCaptchaV3TaskProxyLess => `gRecaptchaResponse`.
   - HCaptchaTaskProxyLess => `gRecaptchaResponse` (api lo expone igual).
   - AntiTurnstileTaskProxyLess => `token`.
   - ImageToTextTask => `text`.

Costes aproximados Q4 2025 (clientKey publico):
- reCAPTCHA v2: USD 0.80 / 1k => 0.08 cents/solve
- reCAPTCHA v3: USD 1.20 / 1k => 0.12 cents/solve
- hCaptcha:    USD 1.00 / 1k => 0.10 cents/solve
- Turnstile:   USD 0.80 / 1k => 0.08 cents/solve
- Imagen:      USD 0.30 / 1k => 0.03 cents/solve
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

DEFAULT_BASE_URL = "https://api.capsolver.com"


class CapSolverAdapter(ICaptchaSolver):
    """Adapter HTTP para CapSolver."""

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_BASE_URL,
        poll_interval_seconds: float = 3.0,
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
        self._log = structlog.get_logger("capsolver_adapter")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def solve_recaptcha_v2(self, *, site_key: str, page_url: str) -> str:
        task = {
            "type": "ReCaptchaV2TaskProxyLess",
            "websiteURL": page_url,
            "websiteKey": site_key,
        }
        return await self._run_task(task, solution_field="gRecaptchaResponse")

    async def solve_recaptcha_v3(
        self,
        *,
        site_key: str,
        page_url: str,
        action: str,
        min_score: float,
    ) -> str:
        task = {
            "type": "ReCaptchaV3TaskProxyLess",
            "websiteURL": page_url,
            "websiteKey": site_key,
            "pageAction": action,
            "minScore": min_score,
        }
        return await self._run_task(task, solution_field="gRecaptchaResponse")

    async def solve_hcaptcha(self, *, site_key: str, page_url: str) -> str:
        task = {
            "type": "HCaptchaTaskProxyLess",
            "websiteURL": page_url,
            "websiteKey": site_key,
        }
        return await self._run_task(task, solution_field="gRecaptchaResponse")

    async def solve_cloudflare_turnstile(self, *, site_key: str, page_url: str) -> str:
        task = {
            "type": "AntiTurnstileTaskProxyLess",
            "websiteURL": page_url,
            "websiteKey": site_key,
        }
        return await self._run_task(task, solution_field="token")

    async def solve_image_text(self, *, image_b64: str, hint: str) -> str:
        task: dict[str, Any] = {
            "type": "ImageToTextTask",
            "body": image_b64,
        }
        if hint:
            task["module"] = "common"
            task["case"] = hint
        return await self._run_task(task, solution_field="text")

    async def _run_task(self, task: dict[str, Any], *, solution_field: str) -> str:
        if not self._api_key:
            raise CaptchaSolverError("capsolver: api_key vacia")

        task_id = await self._create_task(task)
        return await self._poll_task(task_id, solution_field=solution_field)

    async def _create_task(self, task: dict[str, Any]) -> str:
        url = f"{self._base_url}/createTask"
        payload = {"clientKey": self._api_key, "task": task}
        try:
            response = await self._http.post(
                url,
                json=payload,
                timeout=self._request_timeout,
            )
        except httpx.HTTPError as exc:
            raise CaptchaSolverError(f"capsolver createTask request fallo: {exc}") from exc

        if response.status_code >= 400:
            raise CaptchaSolverError(
                f"capsolver createTask status={response.status_code} body={response.text[:200]}",
            )

        data: dict[str, Any] = response.json()
        if data.get("errorId", 0) != 0:
            raise CaptchaSolverError(
                f"capsolver createTask error={data.get('errorCode')} "
                f"desc={data.get('errorDescription')}",
            )
        task_id = data.get("taskId")
        if not isinstance(task_id, str) or not task_id:
            raise CaptchaSolverError(f"capsolver createTask sin taskId: {data}")
        return task_id

    async def _poll_task(self, task_id: str, *, solution_field: str) -> str:
        url = f"{self._base_url}/getTaskResult"
        payload = {"clientKey": self._api_key, "taskId": task_id}
        deadline = asyncio.get_event_loop().time() + self._solve_timeout

        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(self._poll_interval)
            try:
                response = await self._http.post(
                    url,
                    json=payload,
                    timeout=self._request_timeout,
                )
            except httpx.HTTPError as exc:
                self._log.warning(
                    "capsolver.poll_request_failed",
                    task_id=task_id,
                    error=str(exc),
                )
                continue

            if response.status_code >= 400:
                self._log.warning(
                    "capsolver.poll_status_error",
                    task_id=task_id,
                    status=response.status_code,
                )
                continue

            data: dict[str, Any] = response.json()
            if data.get("errorId", 0) != 0:
                raise CaptchaSolverError(
                    f"capsolver getTaskResult error={data.get('errorCode')} "
                    f"desc={data.get('errorDescription')}",
                )

            status = data.get("status")
            if status == "ready":
                solution = data.get("solution") or {}
                value = solution.get(solution_field)
                if not isinstance(value, str) or not value:
                    raise CaptchaSolverError(
                        f"capsolver solucion vacia para campo={solution_field}: {solution}",
                    )
                return value
            if status not in {"processing", "idle"}:
                raise CaptchaSolverError(f"capsolver status inesperado: {status}")

        raise CaptchaSolverError(
            f"capsolver timeout esperando solucion task_id={task_id} "
            f"tras {self._solve_timeout}s",
        )
