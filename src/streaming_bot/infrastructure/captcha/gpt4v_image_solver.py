"""Gpt4vImageSolver: ICaptchaSolver basado en LLM multimodal.

Pensado como FALLBACK de imagen para los reCAPTCHA residuales tipo
"select all squares with traffic lights / motorcycles / buses..." cuando
los providers especializados (CapSolver / 2Captcha) no responden a tiempo.

Soporta dos backends:
- OpenAI Chat Completions API con `gpt-4o` (vision).
- Anthropic Messages API con `claude-sonnet-4-5` (vision).

SOLO implementa `solve_image_text`. Los demas metodos lanzan
`NotImplementedError` con un mensaje claro: este solver no sabe firmar
tokens reCAPTCHA / hCaptcha / Turnstile, esos requieren un solver
especializado que ejecute el flow JS interno (CapSolver / 2Captcha).

Coste aproximado por imagen (Q4 2025, gpt-4o):
- ~ USD 0.005 - 0.015 por solve (depende de tokens de entrada/salida).
- Lo modelamos como 0.50 cents/solve por defecto en el router.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, NoReturn

import httpx
import structlog

from streaming_bot.domain.ports.captcha_solver import (
    CaptchaSolverError,
    ICaptchaSolver,
)


class Gpt4vBackend(str, Enum):
    """Backend LLM multimodal a usar."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"


_DEFAULT_PROMPT = (
    "Resuelve el siguiente CAPTCHA. Si la pista pide seleccionar tiles, "
    "devuelve los indices (1..9 contando de izquierda a derecha y arriba "
    "a abajo, separados por coma). Si la pista pide texto, devuelve "
    "EXCLUSIVAMENTE los caracteres del CAPTCHA, sin explicaciones, sin "
    "espacios y sin puntuacion."
)


class Gpt4vImageSolver(ICaptchaSolver):
    """Solver de imagen via OpenAI o Anthropic vision."""

    def __init__(
        self,
        *,
        api_key: str,
        backend: Gpt4vBackend = Gpt4vBackend.OPENAI,
        model: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        request_timeout_seconds: float = 60.0,
        prompt: str = _DEFAULT_PROMPT,
    ) -> None:
        self._api_key = api_key
        self._backend = backend
        self._model = model or self._default_model_for(backend)
        self._request_timeout = request_timeout_seconds
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=request_timeout_seconds)
        self._prompt = prompt
        self._log = structlog.get_logger("gpt4v_image_solver").bind(backend=backend.value)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    @staticmethod
    def _default_model_for(backend: Gpt4vBackend) -> str:
        if backend is Gpt4vBackend.OPENAI:
            return "gpt-4o"
        return "claude-sonnet-4-5"

    async def solve_recaptcha_v2(self, *, site_key: str, page_url: str) -> str:
        self._unsupported("solve_recaptcha_v2", site_key=site_key, page_url=page_url)

    async def solve_recaptcha_v3(
        self,
        *,
        site_key: str,
        page_url: str,
        action: str,
        min_score: float,
    ) -> str:
        self._unsupported(
            "solve_recaptcha_v3",
            site_key=site_key,
            page_url=page_url,
            action=action,
            min_score=min_score,
        )

    async def solve_hcaptcha(self, *, site_key: str, page_url: str) -> str:
        self._unsupported("solve_hcaptcha", site_key=site_key, page_url=page_url)

    async def solve_cloudflare_turnstile(self, *, site_key: str, page_url: str) -> str:
        self._unsupported(
            "solve_cloudflare_turnstile",
            site_key=site_key,
            page_url=page_url,
        )

    async def solve_image_text(self, *, image_b64: str, hint: str) -> str:
        if not self._api_key:
            raise CaptchaSolverError(f"gpt4v ({self._backend.value}): api_key vacia")
        if not image_b64:
            raise CaptchaSolverError("gpt4v: image_b64 vacio")

        if self._backend is Gpt4vBackend.OPENAI:
            return await self._solve_openai(image_b64=image_b64, hint=hint)
        return await self._solve_anthropic(image_b64=image_b64, hint=hint)

    async def _solve_openai(self, *, image_b64: str, hint: str) -> str:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        instruction = self._prompt if not hint else f"{self._prompt}\nPista: {hint}"
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 64,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_b64}",
                            },
                        },
                    ],
                },
            ],
        }
        data = await self._post_json(url=url, headers=headers, payload=payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise CaptchaSolverError(f"gpt4v openai respuesta inesperada: {data}") from exc
        if not isinstance(content, str) or not content.strip():
            raise CaptchaSolverError(f"gpt4v openai respuesta vacia: {data}")
        return content.strip()

    async def _solve_anthropic(self, *, image_b64: str, hint: str) -> str:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        instruction = self._prompt if not hint else f"{self._prompt}\nPista: {hint}"
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 64,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": instruction},
                    ],
                },
            ],
        }
        data = await self._post_json(url=url, headers=headers, payload=payload)
        try:
            blocks = data["content"]
            text_block = next(b for b in blocks if b.get("type") == "text")
            content = text_block.get("text", "")
        except (KeyError, IndexError, TypeError, StopIteration) as exc:
            raise CaptchaSolverError(f"gpt4v anthropic respuesta inesperada: {data}") from exc
        if not isinstance(content, str) or not content.strip():
            raise CaptchaSolverError(f"gpt4v anthropic respuesta vacia: {data}")
        return content.strip()

    async def _post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response = await self._http.post(
                url,
                headers=headers,
                json=payload,
                timeout=self._request_timeout,
            )
        except httpx.HTTPError as exc:
            raise CaptchaSolverError(f"gpt4v request fallo: {exc}") from exc

        if response.status_code >= 400:
            raise CaptchaSolverError(
                f"gpt4v status={response.status_code} body={response.text[:200]}",
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise CaptchaSolverError(
                f"gpt4v respuesta no-JSON: {response.text[:200]}",
            ) from exc
        if not isinstance(data, dict):
            raise CaptchaSolverError(f"gpt4v JSON inesperado: {data!r}")
        return data

    def _unsupported(self, method: str, **_: object) -> NoReturn:
        msg = (
            f"Gpt4vImageSolver no implementa {method}: usa CapSolver o "
            "2Captcha para tokens reCAPTCHA/hCaptcha/Turnstile."
        )
        self._log.debug("gpt4v.unsupported_method", method=method)
        raise NotImplementedError(msg)
