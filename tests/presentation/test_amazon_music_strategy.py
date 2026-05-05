"""Tests de AmazonMusicStrategy.

Mockeamos IBrowserSession / IRichBrowserSession con AsyncMock. Cubrimos:
is_logged_in, login (success, captcha con/sin solver, 2FA, error),
perform_action, helpers de player y engagement.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from streaming_bot.domain.entities import Account
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.domain.value_objects import Country
from streaming_bot.presentation.strategies import amazon_music_selectors as sel
from streaming_bot.presentation.strategies.amazon_music import AmazonMusicStrategy


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)


def _account() -> Account:
    return Account.new(username="user@amazon", password="hunter2", country=Country.US)


class TestIsLoggedIn:
    async def test_returns_true_when_avatar_present(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        strategy = AmazonMusicStrategy()

        assert await strategy.is_logged_in(page) is True

    async def test_returns_false_when_neither_avatar_nor_library(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no")
        strategy = AmazonMusicStrategy()

        assert await strategy.is_logged_in(page) is False


class TestLogin:
    async def test_login_success_two_step_flow(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector in (
                sel.SIGN_IN_LINK,
                sel.LOGIN_EMAIL,
                sel.LOGIN_PASSWORD,
                sel.USER_AVATAR,
            ):
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = AmazonMusicStrategy()

        await strategy.login(page, _account())

        page.fill.assert_any_await(sel.LOGIN_EMAIL, "user@amazon")
        page.fill.assert_any_await(sel.LOGIN_PASSWORD, "hunter2")
        page.click.assert_any_await(sel.LOGIN_SUBMIT)

    async def test_login_form_missing_raises_target_site_error(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no form")
        strategy = AmazonMusicStrategy()

        with pytest.raises(TargetSiteError, match="email"):
            await strategy.login(page, _account())

    async def test_login_raises_when_captcha_without_solver(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector in (sel.LOGIN_EMAIL, sel.LOGIN_PASSWORD):
                return
            if selector == sel.IMAGE_CAPTCHA:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = AmazonMusicStrategy(captcha_solver=None)

        with pytest.raises(AuthenticationError, match="captcha"):
            await strategy.login(page, _account())

    async def test_login_uses_captcha_solver_and_eventually_succeeds(self) -> None:
        page = AsyncMock()
        captcha_seen = {"n": 0}

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector in (sel.LOGIN_EMAIL, sel.LOGIN_PASSWORD):
                return
            if selector == sel.IMAGE_CAPTCHA and captcha_seen["n"] == 0:
                captcha_seen["n"] += 1
                return
            if selector == sel.USER_AVATAR and captcha_seen["n"] == 1:
                return
            raise TimeoutError("nada")

        async def _evaluate(_expr: str) -> object:
            # Devolvemos un base64 de relleno; el mock del solver no valida.
            return "ZmFrZS1iNjQ="

        page.wait_for_selector.side_effect = _wait
        page.evaluate.side_effect = _evaluate

        solver = AsyncMock()
        solver.solve_image_text.return_value = "ABCD"
        strategy = AmazonMusicStrategy(captcha_solver=solver)

        await strategy.login(page, _account())

        solver.solve_image_text.assert_awaited_with(
            image_b64="ZmFrZS1iNjQ=",
            hint="amazon captcha letters",
        )
        page.fill.assert_any_await(sel.IMAGE_CAPTCHA_INPUT, "ABCD")

    async def test_login_raises_on_two_factor(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector in (sel.LOGIN_EMAIL, sel.LOGIN_PASSWORD):
                return
            if selector == sel.TWO_FACTOR_OTP:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = AmazonMusicStrategy()

        with pytest.raises(AuthenticationError, match="2FA"):
            await strategy.login(page, _account())

    async def test_login_raises_on_login_error(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector in (sel.LOGIN_EMAIL, sel.LOGIN_PASSWORD):
                return
            if selector == sel.LOGIN_ERROR:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = AmazonMusicStrategy()

        with pytest.raises(AuthenticationError, match="rechazado"):
            await strategy.login(page, _account())


class TestPerformAction:
    async def test_clicks_play_button(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        strategy = AmazonMusicStrategy()

        await strategy.perform_action(page, "https://music.amazon.com/albums/x", 35)

        page.goto.assert_awaited_with(
            "https://music.amazon.com/albums/x",
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
        strategy = AmazonMusicStrategy()

        await strategy.perform_action(page, "https://music.amazon.com/albums/x", 1)
        page.click.assert_any_await(sel.PLAY_PAUSE)

    async def test_raises_target_site_error_when_no_player(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("nada")
        strategy = AmazonMusicStrategy()

        with pytest.raises(TargetSiteError, match="reproduccion"):
            await strategy.perform_action(page, "https://music.amazon.com/albums/x", 1)


class TestPlayerHelpers:
    async def test_wait_for_player_ready_raises_on_timeout(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("nada")
        strategy = AmazonMusicStrategy()

        with pytest.raises(TargetSiteError, match="player no llego"):
            await strategy.wait_for_player_ready(page)

    async def test_get_current_track_uri_returns_synthetic_uri(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = "B0XXXASIN"
        strategy = AmazonMusicStrategy()

        assert await strategy.get_current_track_uri(page) == "amazon:track:B0XXXASIN"

    async def test_get_current_artist_uri_extracts_id(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = "/artists/A1B2C3"
        strategy = AmazonMusicStrategy()

        assert await strategy.get_current_artist_uri(page) == "amazon:artist:A1B2C3"

    async def test_get_current_artist_uri_none_on_empty(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = None
        strategy = AmazonMusicStrategy()

        assert await strategy.get_current_artist_uri(page) is None


class TestEngagementHelpers:
    async def test_like_returns_true_when_visible(self) -> None:
        page = AsyncMock()
        page.is_visible.return_value = True
        strategy = AmazonMusicStrategy()

        assert await strategy.like_current_track(page) is True
        page.human_click.assert_awaited_with(sel.LIKE_BUTTON)

    async def test_add_to_playlist_uses_correct_selector(self) -> None:
        page = AsyncMock()
        page.is_visible.return_value = True
        strategy = AmazonMusicStrategy()

        assert await strategy.add_to_playlist(page) is True
        page.human_click.assert_awaited_with(sel.ADD_TO_PLAYLIST)

    async def test_follow_artist_returns_false_when_hidden(self) -> None:
        page = AsyncMock()
        page.is_visible.return_value = False
        strategy = AmazonMusicStrategy()

        assert await strategy.follow_current_artist(page) is False
        page.human_click.assert_not_awaited()
