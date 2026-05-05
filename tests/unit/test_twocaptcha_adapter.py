"""Tests del TwoCaptchaAdapter usando httpx.MockTransport."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from streaming_bot.domain.ports.captcha_solver import CaptchaSolverError
from streaming_bot.infrastructure.captcha.twocaptcha_adapter import (
    TwoCaptchaAdapter,
)


def _make_adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    api_key: str = "test-key",
    poll_interval: float = 0.0,
    solve_timeout: float = 5.0,
) -> TwoCaptchaAdapter:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return TwoCaptchaAdapter(
        api_key=api_key,
        http_client=client,
        poll_interval_seconds=poll_interval,
        solve_timeout_seconds=solve_timeout,
        request_timeout_seconds=5.0,
    )


def _form_body(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(request.read().decode())


class TestTwoCaptchaAdapterRecaptchaV2:
    async def test_solve_recaptcha_v2_happy_path(self) -> None:
        seen_methods: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/in.php":
                form = _form_body(request)
                seen_methods.append(form["method"][0])
                assert form["googlekey"] == ["6Lc-test"]
                assert form["pageurl"] == ["https://example.com/login"]
                return httpx.Response(200, json={"status": 1, "request": "12345"})
            if request.url.path == "/res.php":
                return httpx.Response(200, json={"status": 1, "request": "TOKEN_OK"})
            return httpx.Response(404)

        adapter = _make_adapter(handler)
        token = await adapter.solve_recaptcha_v2(
            site_key="6Lc-test",
            page_url="https://example.com/login",
        )
        assert token == "TOKEN_OK"
        assert seen_methods == ["userrecaptcha"]
        await adapter.aclose()

    async def test_in_php_error_status_zero(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"status": 0, "request": "ERROR_KEY_DOES_NOT_EXIST"},
            )

        adapter = _make_adapter(handler)
        with pytest.raises(CaptchaSolverError, match="ERROR_KEY_DOES_NOT_EXIST"):
            await adapter.solve_recaptcha_v2(
                site_key="x",
                page_url="https://example.com",
            )
        await adapter.aclose()

    async def test_polling_not_ready_then_ready(self) -> None:
        responses: Iterator[dict[str, Any]] = iter(
            [
                {"status": 0, "request": "CAPCHA_NOT_READY"},
                {"status": 0, "request": "CAPCHA_NOT_READY"},
                {"status": 1, "request": "FINAL_TOKEN"},
            ],
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/in.php":
                return httpx.Response(200, json={"status": 1, "request": "id-1"})
            return httpx.Response(200, json=next(responses))

        adapter = _make_adapter(handler)
        token = await adapter.solve_recaptcha_v2(
            site_key="x",
            page_url="https://example.com",
        )
        assert token == "FINAL_TOKEN"
        await adapter.aclose()

    async def test_solve_timeout_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/in.php":
                return httpx.Response(200, json={"status": 1, "request": "id-1"})
            return httpx.Response(200, json={"status": 0, "request": "CAPCHA_NOT_READY"})

        adapter = _make_adapter(handler, poll_interval=0.01, solve_timeout=0.05)
        with pytest.raises(CaptchaSolverError, match="timeout"):
            await adapter.solve_recaptcha_v2(
                site_key="x",
                page_url="https://example.com",
            )
        await adapter.aclose()

    async def test_res_php_error_propagates(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/in.php":
                return httpx.Response(200, json={"status": 1, "request": "id-1"})
            return httpx.Response(200, json={"status": 0, "request": "ERROR_CAPTCHA_UNSOLVABLE"})

        adapter = _make_adapter(handler)
        with pytest.raises(CaptchaSolverError, match="ERROR_CAPTCHA_UNSOLVABLE"):
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


class TestTwoCaptchaAdapterOtherTypes:
    async def test_recaptcha_v3_sets_version_action_score(self) -> None:
        captured: dict[str, list[str]] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/in.php":
                captured.update(_form_body(request))
                return httpx.Response(200, json={"status": 1, "request": "id-2"})
            return httpx.Response(200, json={"status": 1, "request": "V3_TOKEN"})

        adapter = _make_adapter(handler)
        token = await adapter.solve_recaptcha_v3(
            site_key="6Lc-v3",
            page_url="https://example.com/x",
            action="login",
            min_score=0.7,
        )
        assert token == "V3_TOKEN"
        assert captured["version"] == ["v3"]
        assert captured["action"] == ["login"]
        assert captured["min_score"] == ["0.7"]
        await adapter.aclose()

    async def test_hcaptcha_uses_sitekey_field(self) -> None:
        captured: dict[str, list[str]] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/in.php":
                captured.update(_form_body(request))
                return httpx.Response(200, json={"status": 1, "request": "id-3"})
            return httpx.Response(200, json={"status": 1, "request": "HC_TOKEN"})

        adapter = _make_adapter(handler)
        token = await adapter.solve_hcaptcha(
            site_key="hc-key",
            page_url="https://example.com",
        )
        assert token == "HC_TOKEN"
        assert captured["method"] == ["hcaptcha"]
        assert captured["sitekey"] == ["hc-key"]
        await adapter.aclose()

    async def test_turnstile_method_and_sitekey(self) -> None:
        captured: dict[str, list[str]] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/in.php":
                captured.update(_form_body(request))
                return httpx.Response(200, json={"status": 1, "request": "id-4"})
            return httpx.Response(200, json={"status": 1, "request": "TS_TOKEN"})

        adapter = _make_adapter(handler)
        token = await adapter.solve_cloudflare_turnstile(
            site_key="0x4AAA",
            page_url="https://example.com",
        )
        assert token == "TS_TOKEN"
        assert captured["method"] == ["turnstile"]
        assert captured["sitekey"] == ["0x4AAA"]
        await adapter.aclose()

    async def test_image_text_uses_base64_method(self) -> None:
        captured: dict[str, list[str]] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/in.php":
                captured.update(_form_body(request))
                return httpx.Response(200, json={"status": 1, "request": "id-5"})
            return httpx.Response(200, json={"status": 1, "request": "ABCDE"})

        adapter = _make_adapter(handler)
        text = await adapter.solve_image_text(
            image_b64="aGVsbG8=",
            hint="caracteres del texto",
        )
        assert text == "ABCDE"
        assert captured["method"] == ["base64"]
        assert captured["body"] == ["aGVsbG8="]
        assert captured["textinstructions"] == ["caracteres del texto"]
        await adapter.aclose()
