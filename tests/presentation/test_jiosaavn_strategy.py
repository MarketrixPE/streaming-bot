"""Tests de JioSaavnStrategy.

No tocamos browser real: mockeamos IBrowserSession / IRichBrowserSession
con AsyncMock. Verificamos:
- is_logged_in: True con avatar visible, False si timeout.
- login: rellena email + password + click submit; lanza
  AuthenticationError ante captcha o credenciales rechazadas;
  TargetSiteError si el form no aparece.
- perform_action: navega + click play + duerme >= 35s.
- helpers de player: extraen URI / artista correctamente y devuelven None
  ante errores.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from streaming_bot.domain.entities import Account
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.domain.value_objects import Country
from streaming_bot.presentation.strategies import jiosaavn_selectors as sel
from streaming_bot.presentation.strategies.jiosaavn import JioSaavnStrategy


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)


def _account() -> Account:
    return Account.new(username="user@jiosaavn", password="hunter2", country=Country.IN)


class TestIsLoggedIn:
    async def test_returns_true_when_avatar_visible(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        strategy = JioSaavnStrategy()

        assert await strategy.is_logged_in(page) is True
        page.wait_for_selector.assert_awaited_with(sel.USER_AVATAR, timeout_ms=3000)

    async def test_returns_false_on_timeout(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no avatar")
        strategy = JioSaavnStrategy()

        assert await strategy.is_logged_in(page) is False


class TestLogin:
    async def test_login_fills_form_and_clicks_submit(self) -> None:
        page = AsyncMock()
        wait_calls: list[str] = []

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            wait_calls.append(selector)
            if selector == sel.LOGIN_EMAIL:
                return
            if selector == sel.USER_AVATAR and len(wait_calls) > 1:
                return
            raise TimeoutError("no aun")

        page.wait_for_selector.side_effect = _wait

        strategy = JioSaavnStrategy()
        await strategy.login(page, _account())

        page.fill.assert_any_await(sel.LOGIN_EMAIL, "user@jiosaavn")
        page.fill.assert_any_await(sel.LOGIN_PASSWORD, "hunter2")
        page.click.assert_awaited_with(sel.LOGIN_SUBMIT)
        assert sel.LOGIN_EMAIL in wait_calls
        assert sel.USER_AVATAR in wait_calls

    async def test_login_raises_target_site_error_when_form_missing(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no form")
        strategy = JioSaavnStrategy()

        with pytest.raises(TargetSiteError, match="login form"):
            await strategy.login(page, _account())

    async def test_login_raises_authentication_error_on_captcha(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector == sel.LOGIN_EMAIL:
                return
            if selector == sel.USER_AVATAR:
                raise TimeoutError("no avatar")
            if selector == sel.CAPTCHA_HINT:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = JioSaavnStrategy()

        with pytest.raises(AuthenticationError, match="captcha"):
            await strategy.login(page, _account())

    async def test_login_raises_authentication_error_on_login_error(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            if selector == sel.LOGIN_EMAIL:
                return
            if selector == sel.USER_AVATAR:
                raise TimeoutError("no avatar")
            if selector == sel.CAPTCHA_HINT:
                raise TimeoutError("no captcha")
            if selector == sel.LOGIN_ERROR:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = JioSaavnStrategy()

        with pytest.raises(AuthenticationError, match="credenciales"):
            await strategy.login(page, _account())


class TestPerformAction:
    async def test_clicks_play_icon(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        strategy = JioSaavnStrategy()

        await strategy.perform_action(page, "https://www.jiosaavn.com/song/x", 35)

        page.goto.assert_awaited_with(
            "https://www.jiosaavn.com/song/x",
            wait_until="domcontentloaded",
        )
        page.click.assert_any_await(sel.PLAY_ICON)

    async def test_raises_target_site_error_on_play_failure(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no player")
        strategy = JioSaavnStrategy()

        with pytest.raises(TargetSiteError, match="reproduccion"):
            await strategy.perform_action(page, "https://x", 35)


class TestPlayerHelpers:
    async def test_wait_for_player_ready_raises_when_widget_missing(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no widget")
        strategy = JioSaavnStrategy()

        with pytest.raises(TargetSiteError, match="player"):
            await strategy.wait_for_player_ready(page)

    async def test_get_current_track_uri_returns_canonical_uri(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = "abc123"
        strategy = JioSaavnStrategy()

        assert await strategy.get_current_track_uri(page) == "jiosaavn:song:abc123"

    async def test_get_current_track_uri_returns_none_without_id(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = None
        strategy = JioSaavnStrategy()

        assert await strategy.get_current_track_uri(page) is None

    async def test_get_current_track_uri_returns_none_on_exception(self) -> None:
        page = AsyncMock()
        page.evaluate.side_effect = RuntimeError("boom")
        strategy = JioSaavnStrategy()

        assert await strategy.get_current_track_uri(page) is None

    async def test_get_current_artist_uri_extracts_id(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = "/artist/yo-yo-honey-singh/9999"
        strategy = JioSaavnStrategy()

        assert await strategy.get_current_artist_uri(page) == "jiosaavn:artist:9999"

    async def test_get_current_artist_uri_returns_none_without_href(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = None
        strategy = JioSaavnStrategy()

        assert await strategy.get_current_artist_uri(page) is None

    async def test_get_current_artist_uri_returns_none_on_exception(self) -> None:
        page = AsyncMock()
        page.evaluate.side_effect = RuntimeError("boom")
        strategy = JioSaavnStrategy()

        assert await strategy.get_current_artist_uri(page) is None
