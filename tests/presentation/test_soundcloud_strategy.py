"""Tests de SoundcloudStrategy.

Mockeamos `IBrowserSession` y `ICaptchaSolver`. No tocamos un browser real.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from streaming_bot.application.behavior.decision_delay import NullDelayPolicy
from streaming_bot.domain.entities import Account
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.domain.value_objects import Country
from streaming_bot.presentation.strategies.soundcloud import SoundcloudStrategy
from streaming_bot.presentation.strategies.soundcloud_selectors import (
    DATADOME_ATTRIBUTE,
    DATADOME_GLOBAL_SELECTOR,
    DATADOME_IFRAME,
    EMAIL_INPUT,
    FOLLOW_BUTTON,
    HEADER_USER_NAV,
    LIKE_BUTTON,
    PASSWORD_INPUT,
    PLAY_BUTTON,
    REPOST_BUTTON,
    SIGNIN_BUTTON,
    SIGNIN_FORM,
)


def _account() -> Account:
    return Account.new(username="boost@sc", password="hunter2", country=Country.US)


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)


def _strategy(*, captcha: object | None = None) -> SoundcloudStrategy:
    """Strategy con NullDelayPolicy para no introducir delays en tests."""
    return SoundcloudStrategy(
        captcha_solver=captcha,  # type: ignore[arg-type]
        delay_policy=NullDelayPolicy(),
    )


class TestIsLoggedIn:
    async def test_returns_true_when_user_nav_present(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None

        result = await _strategy().is_logged_in(page)

        assert result is True
        page.wait_for_selector.assert_awaited_with(HEADER_USER_NAV, timeout_ms=3_000)

    async def test_returns_false_when_user_nav_missing(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("nope")

        result = await _strategy().is_logged_in(page)

        assert result is False


class TestLogin:
    async def test_login_fills_form_and_clicks_signin(self) -> None:
        page = AsyncMock()
        seen: list[str] = []

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            del timeout_ms
            seen.append(selector)
            datadome_hints = (
                DATADOME_IFRAME,
                DATADOME_ATTRIBUTE,
                DATADOME_GLOBAL_SELECTOR,
            )
            if selector in datadome_hints:
                raise TimeoutError("no datadome")
            if selector == SIGNIN_FORM:
                return
            if selector == HEADER_USER_NAV:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait

        await _strategy().login(page, _account())

        page.fill.assert_any_await(EMAIL_INPUT, "boost@sc")
        page.fill.assert_any_await(PASSWORD_INPUT, "hunter2")
        page.click.assert_awaited_with(SIGNIN_BUTTON)
        assert SIGNIN_FORM in seen
        assert HEADER_USER_NAV in seen

    async def test_login_raises_target_site_error_when_form_missing(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            del timeout_ms
            raise TimeoutError(f"missing {selector}")

        page.wait_for_selector.side_effect = _wait

        with pytest.raises(TargetSiteError, match="signin form"):
            await _strategy().login(page, _account())

    async def test_login_raises_authentication_error_on_datadome_without_solver(
        self,
    ) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            del timeout_ms
            if selector == DATADOME_IFRAME:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        page.evaluate.return_value = None

        with pytest.raises(AuthenticationError, match="datadome"):
            await _strategy().login(page, _account())

    async def test_login_invokes_captcha_solver_on_datadome(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = "SITEKEY-XYZ"

        post_solve_seen: dict[str, int] = {"signin_form": 0, "header_nav": 0}

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            del timeout_ms
            if selector == DATADOME_IFRAME:
                # Reportamos datadome solo en el chequeo inicial; tras el
                # solver el siguiente chequeo cierra la rama.
                if post_solve_seen["signin_form"] == 0:
                    return
                raise TimeoutError("ya resuelto")
            if selector in (DATADOME_ATTRIBUTE, DATADOME_GLOBAL_SELECTOR):
                raise TimeoutError("no datadome")
            if selector == SIGNIN_FORM:
                post_solve_seen["signin_form"] += 1
                return
            if selector == HEADER_USER_NAV:
                post_solve_seen["header_nav"] += 1
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait

        captcha = AsyncMock()
        captcha.solve_cloudflare_turnstile = AsyncMock(return_value="cf-token")
        captcha.solve_image_text = AsyncMock(return_value="image-text")

        await _strategy(captcha=captcha).login(page, _account())

        captcha.solve_cloudflare_turnstile.assert_awaited_once()
        kwargs = captcha.solve_cloudflare_turnstile.await_args.kwargs
        assert kwargs["site_key"] == "SITEKEY-XYZ"


class TestPerformAction:
    async def test_perform_action_clicks_play_button(self) -> None:
        page = AsyncMock()
        datadome_hints = (
            DATADOME_IFRAME,
            DATADOME_ATTRIBUTE,
            DATADOME_GLOBAL_SELECTOR,
        )

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            del timeout_ms
            if selector in datadome_hints:
                raise TimeoutError("no datadome")

        page.wait_for_selector.side_effect = _wait

        await _strategy().perform_action(page, "https://soundcloud.com/x/y", 30)

        page.goto.assert_awaited_with(
            "https://soundcloud.com/x/y",
            wait_until="domcontentloaded",
        )
        page.click.assert_any_await(PLAY_BUTTON)

    async def test_perform_action_falls_back_to_aria_label(self) -> None:
        page = AsyncMock()
        attempts = {"n": 0}

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            del timeout_ms
            attempts["n"] += 1
            datadome_hints = (
                DATADOME_IFRAME,
                DATADOME_ATTRIBUTE,
                DATADOME_GLOBAL_SELECTOR,
            )
            if selector in datadome_hints:
                raise TimeoutError("no datadome")
            if selector == PLAY_BUTTON:
                raise TimeoutError("no primary")

        page.wait_for_selector.side_effect = _wait

        await _strategy().perform_action(page, "https://soundcloud.com/x/y", 1)

        page.click.assert_any_await('[aria-label="Play"]')


class TestBoostActions:
    async def test_like_uses_primary_selector(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None

        await _strategy().like_current_track(page)

        page.click.assert_any_await(LIKE_BUTTON)

    async def test_repost_uses_primary_selector(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None

        await _strategy().repost_current_track(page)

        page.click.assert_any_await(REPOST_BUTTON)

    async def test_follow_uses_primary_selector(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None

        await _strategy().follow_current_artist(page)

        page.click.assert_any_await(FOLLOW_BUTTON)

    async def test_comment_empty_raises(self) -> None:
        page = AsyncMock()

        with pytest.raises(ValueError, match="vacio"):
            await _strategy().comment_current_track(page, "   ")
