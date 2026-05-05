"""Tests del CapSolverAdapter usando httpx.MockTransport."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from streaming_bot.domain.ports.captcha_solver import CaptchaSolverError
from streaming_bot.infrastructure.captcha.capsolver_adapter import (
    CapSolverAdapter,
)


def _make_adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    api_key: str = "test-key",
    poll_interval: float = 0.0,
    solve_timeout: float = 5.0,
) -> CapSolverAdapter:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return CapSolverAdapter(
        api_key=api_key,
        http_client=client,
        poll_interval_seconds=poll_interval,
        solve_timeout_seconds=solve_timeout,
        request_timeout_seconds=5.0,
    )


class TestCapSolverAdapterRecaptchaV2:
    async def test_solve_recaptcha_v2_happy_path(self) -> None:
        seen_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_paths.append(request.url.path)
            if request.url.path == "/createTask":
                body = request.read().decode()
                assert "ReCaptchaV2TaskProxyLess" in body
                assert "test-key" in body
                return httpx.Response(200, json={"errorId": 0, "taskId": "tid-42"})
            if request.url.path == "/getTaskResult":
                return httpx.Response(
                    200,
                    json={
                        "errorId": 0,
                        "status": "ready",
                        "solution": {"gRecaptchaResponse": "TOKEN_OK"},
                    },
                )
            return httpx.Response(404)

        adapter = _make_adapter(handler)
        token = await adapter.solve_recaptcha_v2(
            site_key="6Lc-test",
            page_url="https://example.com/login",
        )
        assert token == "TOKEN_OK"
        assert "/createTask" in seen_paths
        assert "/getTaskResult" in seen_paths
        await adapter.aclose()

    async def test_create_task_error_propagates(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "errorId": 1,
                    "errorCode": "ERROR_KEY_DOES_NOT_EXIST",
                    "errorDescription": "Invalid key",
                },
            )

        adapter = _make_adapter(handler)
        with pytest.raises(CaptchaSolverError, match="ERROR_KEY_DOES_NOT_EXIST"):
            await adapter.solve_recaptcha_v2(
                site_key="x",
                page_url="https://example.com",
            )
        await adapter.aclose()

    async def test_polling_processing_then_ready(self) -> None:
        statuses: Iterator[dict[str, Any]] = iter(
            [
                {"errorId": 0, "status": "processing"},
                {"errorId": 0, "status": "processing"},
                {
                    "errorId": 0,
                    "status": "ready",
                    "solution": {"gRecaptchaResponse": "FINAL"},
                },
            ],
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/createTask":
                return httpx.Response(200, json={"errorId": 0, "taskId": "tid"})
            return httpx.Response(200, json=next(statuses))

        adapter = _make_adapter(handler)
        token = await adapter.solve_recaptcha_v2(
            site_key="x",
            page_url="https://example.com",
        )
        assert token == "FINAL"
        await adapter.aclose()

    async def test_solve_timeout_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/createTask":
                return httpx.Response(200, json={"errorId": 0, "taskId": "tid"})
            return httpx.Response(200, json={"errorId": 0, "status": "processing"})

        adapter = _make_adapter(handler, poll_interval=0.01, solve_timeout=0.05)
        with pytest.raises(CaptchaSolverError, match="timeout"):
            await adapter.solve_recaptcha_v2(
                site_key="x",
                page_url="https://example.com",
            )
        await adapter.aclose()

    async def test_empty_api_key_raises(self) -> None:
        adapter = _make_adapter(lambda _r: httpx.Response(200), api_key="")
        with pytest.raises(CaptchaSolverError, match="api_key vacia"):
            await adapter.solve_recaptcha_v2(
                site_key="x",
                page_url="https://example.com",
            )
        await adapter.aclose()


class TestCapSolverAdapterOtherTypes:
    async def test_recaptcha_v3_includes_action_and_score(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/createTask":
                payload = request.read().decode()
                captured["payload"] = payload
                return httpx.Response(200, json={"errorId": 0, "taskId": "tid"})
            return httpx.Response(
                200,
                json={
                    "errorId": 0,
                    "status": "ready",
                    "solution": {"gRecaptchaResponse": "V3"},
                },
            )

        adapter = _make_adapter(handler)
        token = await adapter.solve_recaptcha_v3(
            site_key="6Lc-v3",
            page_url="https://example.com/x",
            action="login",
            min_score=0.7,
        )
        assert token == "V3"
        assert "ReCaptchaV3TaskProxyLess" in captured["payload"]
        assert "login" in captured["payload"]
        assert "0.7" in captured["payload"]
        await adapter.aclose()

    async def test_hcaptcha_solution_field(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/createTask":
                return httpx.Response(200, json={"errorId": 0, "taskId": "tid"})
            return httpx.Response(
                200,
                json={
                    "errorId": 0,
                    "status": "ready",
                    "solution": {"gRecaptchaResponse": "HC_TOKEN"},
                },
            )

        adapter = _make_adapter(handler)
        token = await adapter.solve_hcaptcha(
            site_key="hc-key",
            page_url="https://example.com",
        )
        assert token == "HC_TOKEN"
        await adapter.aclose()

    async def test_turnstile_uses_token_field(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/createTask":
                return httpx.Response(200, json={"errorId": 0, "taskId": "tid"})
            return httpx.Response(
                200,
                json={
                    "errorId": 0,
                    "status": "ready",
                    "solution": {"token": "TS_TOKEN"},
                },
            )

        adapter = _make_adapter(handler)
        token = await adapter.solve_cloudflare_turnstile(
            site_key="0x4AAA",
            page_url="https://example.com",
        )
        assert token == "TS_TOKEN"
        await adapter.aclose()

    async def test_image_text_uses_text_field(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/createTask":
                return httpx.Response(200, json={"errorId": 0, "taskId": "tid"})
            return httpx.Response(
                200,
                json={
                    "errorId": 0,
                    "status": "ready",
                    "solution": {"text": "ABCDE"},
                },
            )

        adapter = _make_adapter(handler)
        text = await adapter.solve_image_text(
            image_b64="aGVsbG8=",
            hint="caracteres del texto",
        )
        assert text == "ABCDE"
        await adapter.aclose()
