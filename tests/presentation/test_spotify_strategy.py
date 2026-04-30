"""Tests de SpotifyWebPlayerStrategy.

No tocamos un browser real: mockeamos `IBrowserSession`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from streaming_bot.domain.entities import Account
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.domain.value_objects import Country
from streaming_bot.presentation.strategies.spotify import (
    LOGIN_BUTTON,
    LOGIN_PASSWORD,
    LOGIN_USERNAME,
    USER_WIDGET_NAME,
    SpotifyWebPlayerStrategy,
)


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)


def _account() -> Account:
    return Account.new(username="user@spotify", password="hunter2", country=Country.PE)


class TestIsLoggedIn:
    async def test_returns_true_when_user_widget_present(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        strategy = SpotifyWebPlayerStrategy()

        assert await strategy.is_logged_in(page) is True
        page.wait_for_selector.assert_awaited_with(USER_WIDGET_NAME, timeout_ms=3000)

    async def test_returns_false_when_widget_missing(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no widget")
        strategy = SpotifyWebPlayerStrategy()

        assert await strategy.is_logged_in(page) is False


class TestLogin:
    async def test_login_calls_selectors_in_order(self) -> None:
        page = AsyncMock()
        # wait_for_selector: primero acepta el form (LOGIN_USERNAME ok),
        # luego en el bucle el primero que matchea es USER_WIDGET_NAME.
        wait_calls = []

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            wait_calls.append((selector, timeout_ms))
            if selector == USER_WIDGET_NAME and len(wait_calls) > 1:
                return
            if selector == LOGIN_USERNAME:
                return
            raise TimeoutError("no aun")

        page.wait_for_selector.side_effect = _wait

        strategy = SpotifyWebPlayerStrategy()
        await strategy.login(page, _account())

        # El form se completo y el boton se clickeo.
        page.fill.assert_any_await(LOGIN_USERNAME, "user@spotify")
        page.fill.assert_any_await(LOGIN_PASSWORD, "hunter2")
        page.click.assert_awaited_with(LOGIN_BUTTON)

        # Los primeros selectores esperados fueron LOGIN_USERNAME y USER_WIDGET_NAME.
        selectors_visited = [c[0] for c in wait_calls]
        assert LOGIN_USERNAME in selectors_visited
        assert USER_WIDGET_NAME in selectors_visited

    async def test_login_raises_authentication_error_on_captcha(self) -> None:
        page = AsyncMock()
        captcha_selector = '[data-testid="captcha"]'

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector == LOGIN_USERNAME:
                return
            if selector == USER_WIDGET_NAME:
                raise TimeoutError("no widget")
            if selector == captcha_selector:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = SpotifyWebPlayerStrategy()

        with pytest.raises(AuthenticationError, match="captcha"):
            await strategy.login(page, _account())

    async def test_login_raises_authentication_error_on_login_failed(self) -> None:
        page = AsyncMock()
        captcha_selector = '[data-testid="captcha"]'
        failed_selector = '[data-testid="login-error"]'

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector == LOGIN_USERNAME:
                return
            if selector == USER_WIDGET_NAME:
                raise TimeoutError("no widget")
            if selector == captcha_selector:
                raise TimeoutError("no captcha")
            if selector == failed_selector:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = SpotifyWebPlayerStrategy()

        with pytest.raises(AuthenticationError, match="credenciales"):
            await strategy.login(page, _account())


class TestPerformAction:
    async def test_perform_action_clicks_playlist_play_button(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        strategy = SpotifyWebPlayerStrategy()

        await strategy.perform_action(page, "https://open.spotify.com/playlist/x", 35)

        page.goto.assert_awaited_with(
            "https://open.spotify.com/playlist/x",
            wait_until="domcontentloaded",
        )
        page.click.assert_any_await('[data-testid="play-button"]')

    async def test_perform_action_falls_back_to_play_pause(self) -> None:
        page = AsyncMock()
        # Primer wait_for_selector falla, segundo (PLAY_PAUSE) funciona.
        call_count = {"n": 0}

        async def _wait(_selector: str, *, timeout_ms: int = 30_000) -> None:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise TimeoutError("no playlist button")

        page.wait_for_selector.side_effect = _wait
        strategy = SpotifyWebPlayerStrategy()

        await strategy.perform_action(page, "https://x", 1)
        page.click.assert_any_await('[data-testid="control-button-playpause"]')


class TestWaitForPlayerReady:
    async def test_raises_target_site_error_when_widget_missing(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no widget")
        strategy = SpotifyWebPlayerStrategy()

        with pytest.raises(TargetSiteError, match="player no llego"):
            await strategy.wait_for_player_ready(page)


class TestHelpers:
    async def test_get_current_track_uri_returns_attribute(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = "spotify:track:abc"
        strategy = SpotifyWebPlayerStrategy()

        result = await strategy.get_current_track_uri(page)
        assert result == "spotify:track:abc"

    async def test_get_current_track_uri_returns_none_on_failure(self) -> None:
        page = AsyncMock()
        page.evaluate.side_effect = RuntimeError("boom")
        strategy = SpotifyWebPlayerStrategy()

        result = await strategy.get_current_track_uri(page)
        assert result is None

    async def test_get_current_artist_uri_extracts_id(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = "/artist/bunny42"
        strategy = SpotifyWebPlayerStrategy()

        result = await strategy.get_current_artist_uri(page)
        assert result == "spotify:artist:bunny42"

    async def test_get_current_artist_uri_returns_none_without_href(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = None
        strategy = SpotifyWebPlayerStrategy()

        assert await strategy.get_current_artist_uri(page) is None

    async def test_get_current_artist_uri_returns_none_on_exception(self) -> None:
        page = AsyncMock()
        page.evaluate.side_effect = RuntimeError("boom")
        strategy = SpotifyWebPlayerStrategy()

        assert await strategy.get_current_artist_uri(page) is None

    async def test_login_form_missing_raises_target_site_error(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no form")
        strategy = SpotifyWebPlayerStrategy()

        with pytest.raises(TargetSiteError, match="login form"):
            await strategy.login(page, _account())
