"""Tests de TidalStrategy.

Mockeamos IBrowserSession / IRichBrowserSession con AsyncMock. Cubrimos:
is_logged_in, login (success, captcha sin solver, error), perform_action,
helpers de player y engagement, y verify_hifi_tier.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from streaming_bot.domain.entities import Account
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.domain.value_objects import Country
from streaming_bot.presentation.strategies import tidal_selectors as sel
from streaming_bot.presentation.strategies.tidal import TidalStrategy


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)


def _account() -> Account:
    return Account.new(username="user@tidal", password="hunter2", country=Country.US)


class TestIsLoggedIn:
    async def test_returns_true_when_avatar_present(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        strategy = TidalStrategy()

        assert await strategy.is_logged_in(page) is True

    async def test_returns_false_when_avatar_missing(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no")
        strategy = TidalStrategy()

        assert await strategy.is_logged_in(page) is False


class TestLogin:
    async def test_login_success_single_step_form(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector in (sel.LOGIN_EMAIL, sel.USER_AVATAR):
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = TidalStrategy()

        await strategy.login(page, _account())

        page.fill.assert_any_await(sel.LOGIN_EMAIL, "user@tidal")
        page.fill.assert_any_await(sel.LOGIN_PASSWORD, "hunter2")
        page.click.assert_awaited_with(sel.LOGIN_BUTTON)

    async def test_login_form_missing_raises_target_site_error(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no form")
        strategy = TidalStrategy()

        with pytest.raises(TargetSiteError, match="login form"):
            await strategy.login(page, _account())

    async def test_login_raises_on_login_error(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector == sel.LOGIN_EMAIL:
                return
            if selector == sel.LOGIN_ERROR:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = TidalStrategy()

        with pytest.raises(AuthenticationError, match="rechazado"):
            await strategy.login(page, _account())

    async def test_login_raises_when_captcha_with_solver(self) -> None:
        page = AsyncMock()
        captcha_selector = 'iframe[src*="hcaptcha.com"], iframe[src*="turnstile"]'

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector == sel.LOGIN_EMAIL:
                return
            if selector == captcha_selector:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        solver = AsyncMock()
        strategy = TidalStrategy(captcha_solver=solver)

        with pytest.raises(AuthenticationError, match="warming"):
            await strategy.login(page, _account())

    async def test_login_no_completion_raises_timeout(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector == sel.LOGIN_EMAIL:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = TidalStrategy()

        with pytest.raises(AuthenticationError, match="tiempo esperado"):
            await strategy.login(page, _account())


class TestPerformAction:
    async def test_clicks_play_button(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        strategy = TidalStrategy()

        await strategy.perform_action(page, "https://listen.tidal.com/album/x", 35)

        page.goto.assert_awaited_with(
            "https://listen.tidal.com/album/x",
            wait_until="domcontentloaded",
        )
        page.click.assert_any_await(sel.PLAY_BUTTON)

    async def test_falls_back_to_play_pause(self) -> None:
        page = AsyncMock()
        call_count = {"n": 0}

        async def _wait(_selector: str, *, timeout_ms: int = 30_000) -> None:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise TimeoutError("no play")

        page.wait_for_selector.side_effect = _wait
        strategy = TidalStrategy()

        await strategy.perform_action(page, "https://listen.tidal.com/album/x", 1)
        page.click.assert_any_await(sel.PLAY_PAUSE)

    async def test_raises_target_site_error_when_no_player(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("nada")
        strategy = TidalStrategy()

        with pytest.raises(TargetSiteError, match="reproduccion"):
            await strategy.perform_action(page, "https://listen.tidal.com/album/x", 1)


class TestPlayerHelpers:
    async def test_wait_for_player_ready_raises_on_timeout(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("nada")
        strategy = TidalStrategy()

        with pytest.raises(TargetSiteError, match="player no llego"):
            await strategy.wait_for_player_ready(page)

    async def test_get_current_track_uri_returns_synthetic_uri(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = "987654321"
        strategy = TidalStrategy()

        assert await strategy.get_current_track_uri(page) == "tidal:track:987654321"

    async def test_get_current_track_uri_none_on_failure(self) -> None:
        page = AsyncMock()
        page.evaluate.side_effect = RuntimeError("boom")
        strategy = TidalStrategy()

        assert await strategy.get_current_track_uri(page) is None

    async def test_get_current_artist_uri_extracts_id(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = "/artist/42"
        strategy = TidalStrategy()

        assert await strategy.get_current_artist_uri(page) == "tidal:artist:42"


class TestEngagementHelpers:
    async def test_like_returns_true_when_visible(self) -> None:
        page = AsyncMock()
        page.is_visible.return_value = True
        strategy = TidalStrategy()

        assert await strategy.like_current_track(page) is True
        page.human_click.assert_awaited_with(sel.LIKE_BUTTON)

    async def test_add_to_playlist_returns_false_when_hidden(self) -> None:
        page = AsyncMock()
        page.is_visible.return_value = False
        strategy = TidalStrategy()

        assert await strategy.add_to_playlist(page) is False

    async def test_follow_artist_uses_correct_selector(self) -> None:
        page = AsyncMock()
        page.is_visible.return_value = True
        strategy = TidalStrategy()

        assert await strategy.follow_current_artist(page) is True
        page.human_click.assert_awaited_with(sel.ARTIST_FOLLOW)


class TestHiFiTier:
    async def test_returns_true_when_badge_says_hifi(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        page.evaluate.return_value = "HiFi Plus"
        strategy = TidalStrategy()

        assert await strategy.verify_hifi_tier(page) is True
        page.goto.assert_awaited_with(
            sel.SUBSCRIPTION_URL,
            wait_until="domcontentloaded",
        )

    async def test_returns_false_when_tier_is_free(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        page.evaluate.return_value = "Free"
        strategy = TidalStrategy()

        assert await strategy.verify_hifi_tier(page) is False

    async def test_returns_false_when_subscription_page_fails(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no badge")
        strategy = TidalStrategy()

        assert await strategy.verify_hifi_tier(page) is False
