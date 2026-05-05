"""Tests de AppleMusicStrategy.

Mockeamos IBrowserSession / IRichBrowserSession con AsyncMock; no tocamos
un browser real. Cubrimos: is_logged_in, login (success, captcha con/sin
solver, 2FA fatal, error), perform_action, helpers de player y engagement.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from streaming_bot.domain.entities import Account
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.domain.value_objects import Country
from streaming_bot.presentation.strategies import apple_music_selectors as sel
from streaming_bot.presentation.strategies.apple_music import AppleMusicStrategy


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)


def _account() -> Account:
    return Account.new(username="user@apple", password="hunter2", country=Country.US)


class TestIsLoggedIn:
    async def test_returns_true_when_avatar_present(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        strategy = AppleMusicStrategy()

        assert await strategy.is_logged_in(page) is True
        page.wait_for_selector.assert_awaited_with(sel.USER_AVATAR, timeout_ms=3000)

    async def test_returns_false_when_avatar_missing(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("nope")
        strategy = AppleMusicStrategy()

        assert await strategy.is_logged_in(page) is False


class TestLogin:
    async def test_login_success_two_step_flow(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            # USERNAME y PASSWORD aparecen; AVATAR aparece en el polling.
            if selector in (sel.LOGIN_USERNAME, sel.LOGIN_PASSWORD, sel.USER_AVATAR):
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = AppleMusicStrategy()

        await strategy.login(page, _account())

        page.fill.assert_any_await(sel.LOGIN_USERNAME, "user@apple")
        page.fill.assert_any_await(sel.LOGIN_PASSWORD, "hunter2")
        page.click.assert_any_await(sel.LOGIN_USERNAME_SUBMIT)

    async def test_login_form_missing_raises_target_site_error(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no form")
        strategy = AppleMusicStrategy()

        with pytest.raises(TargetSiteError, match="login form"):
            await strategy.login(page, _account())

    async def test_password_step_missing_raises_target_site_error(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector == sel.LOGIN_USERNAME:
                return
            raise TimeoutError("password no aparece")

        page.wait_for_selector.side_effect = _wait
        strategy = AppleMusicStrategy()

        with pytest.raises(TargetSiteError, match="password step"):
            await strategy.login(page, _account())

    async def test_login_raises_when_two_factor_detected(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector in (sel.LOGIN_USERNAME, sel.LOGIN_PASSWORD):
                return
            if selector == sel.TWO_FACTOR_HINT:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = AppleMusicStrategy()

        with pytest.raises(AuthenticationError, match="2FA"):
            await strategy.login(page, _account())

    async def test_login_raises_when_captcha_without_solver(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector in (sel.LOGIN_USERNAME, sel.LOGIN_PASSWORD):
                return
            if selector == sel.HCAPTCHA_FRAME:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = AppleMusicStrategy(captcha_solver=None)

        with pytest.raises(AuthenticationError, match="hCaptcha"):
            await strategy.login(page, _account())

    async def test_login_uses_captcha_solver_and_eventually_succeeds(self) -> None:
        page = AsyncMock()
        captcha_seen = {"n": 0}

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector in (sel.LOGIN_USERNAME, sel.LOGIN_PASSWORD):
                return
            if selector == sel.HCAPTCHA_FRAME and captcha_seen["n"] == 0:
                captcha_seen["n"] += 1
                return
            if selector == sel.USER_AVATAR and captcha_seen["n"] == 1:
                return
            raise TimeoutError("nada")

        async def _evaluate(expr: str) -> object:
            if "data-sitekey" in expr:
                return "site-key-fake"
            if "document.location.href" in expr:
                return "https://music.apple.com/login"
            return None

        page.wait_for_selector.side_effect = _wait
        page.evaluate.side_effect = _evaluate

        solver = AsyncMock()
        solver.solve_hcaptcha.return_value = "TOKEN_RESOLVED"
        strategy = AppleMusicStrategy(captcha_solver=solver)

        await strategy.login(page, _account())

        solver.solve_hcaptcha.assert_awaited_with(
            site_key="site-key-fake",
            page_url="https://music.apple.com/login",
        )

    async def test_login_raises_on_login_error(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector in (sel.LOGIN_USERNAME, sel.LOGIN_PASSWORD):
                return
            if selector == sel.LOGIN_ERROR:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = AppleMusicStrategy()

        with pytest.raises(AuthenticationError, match="rechazado"):
            await strategy.login(page, _account())


class TestPerformAction:
    async def test_clicks_play_button(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        strategy = AppleMusicStrategy()

        await strategy.perform_action(page, "https://music.apple.com/album/x", 35)

        page.goto.assert_awaited_with(
            "https://music.apple.com/album/x",
            wait_until="domcontentloaded",
        )
        page.click.assert_any_await(sel.PLAY_BUTTON)

    async def test_falls_back_to_play_pause(self) -> None:
        page = AsyncMock()
        call_count = {"n": 0}

        async def _wait(_selector: str, *, timeout_ms: int = 30_000) -> None:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise TimeoutError("no play button")

        page.wait_for_selector.side_effect = _wait
        strategy = AppleMusicStrategy()

        await strategy.perform_action(page, "https://music.apple.com/album/x", 1)
        page.click.assert_any_await(sel.PLAY_PAUSE)

    async def test_raises_target_site_error_when_no_player(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("nada")
        strategy = AppleMusicStrategy()

        with pytest.raises(TargetSiteError, match="reproduccion"):
            await strategy.perform_action(page, "https://music.apple.com/album/x", 1)


class TestPlayerHelpers:
    async def test_wait_for_player_ready_raises_on_timeout(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("nada")
        strategy = AppleMusicStrategy()

        with pytest.raises(TargetSiteError, match="player no llego"):
            await strategy.wait_for_player_ready(page)

    async def test_get_current_track_uri_returns_synthetic_uri(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = "1234567890"
        strategy = AppleMusicStrategy()

        assert await strategy.get_current_track_uri(page) == "apple:track:1234567890"

    async def test_get_current_track_uri_returns_none_on_failure(self) -> None:
        page = AsyncMock()
        page.evaluate.side_effect = RuntimeError("boom")
        strategy = AppleMusicStrategy()

        assert await strategy.get_current_track_uri(page) is None

    async def test_get_current_artist_uri_extracts_id(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = "/us/artist/bunny/123"
        strategy = AppleMusicStrategy()

        assert await strategy.get_current_artist_uri(page) == "apple:artist:123"

    async def test_get_current_artist_uri_none_on_empty(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = None
        strategy = AppleMusicStrategy()

        assert await strategy.get_current_artist_uri(page) is None


class TestEngagementHelpers:
    async def test_like_returns_true_when_visible(self) -> None:
        page = AsyncMock()
        page.is_visible.return_value = True
        strategy = AppleMusicStrategy()

        assert await strategy.like_current_track(page) is True
        page.human_click.assert_awaited_with(sel.LIKE_BUTTON)

    async def test_like_returns_false_when_hidden(self) -> None:
        page = AsyncMock()
        page.is_visible.return_value = False
        strategy = AppleMusicStrategy()

        assert await strategy.like_current_track(page) is False
        page.human_click.assert_not_awaited()

    async def test_add_to_library_uses_correct_selector(self) -> None:
        page = AsyncMock()
        page.is_visible.return_value = True
        strategy = AppleMusicStrategy()

        assert await strategy.add_to_library(page) is True
        page.human_click.assert_awaited_with(sel.ADD_TO_LIBRARY)

    async def test_follow_artist_uses_correct_selector(self) -> None:
        page = AsyncMock()
        page.is_visible.return_value = True
        strategy = AppleMusicStrategy()

        assert await strategy.follow_current_artist(page) is True
        page.human_click.assert_awaited_with(sel.ARTIST_FOLLOW)
