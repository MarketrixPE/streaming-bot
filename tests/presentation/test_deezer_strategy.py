"""Tests de `DeezerStrategy`.

Mockeamos `IRichBrowserSession` y `ICaptchaSolver` con `AsyncMock` para no
abrir un browser real ni llamar a CapSolver/2Captcha.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from streaming_bot.application.deezer.super_fan_emulation_engine import (
    PlannedSession,
    PlannedTrackPlay,
)
from streaming_bot.domain.entities import Account
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.domain.value_objects import Country
from streaming_bot.presentation.strategies import deezer_selectors as sel
from streaming_bot.presentation.strategies.deezer import DeezerStrategy


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anula asyncio.sleep para no esperar 45+ minutos en tests."""

    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)


def _account() -> Account:
    return Account.new(username="user@deezer.com", password="hunter2", country=Country.FR)


class TestIsLoggedIn:
    async def test_returns_true_when_user_menu_present(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        strategy = DeezerStrategy()
        assert await strategy.is_logged_in(page) is True
        page.wait_for_selector.assert_awaited_with(sel.USER_MENU, timeout_ms=3000)

    async def test_returns_false_when_widget_missing(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no menu")
        strategy = DeezerStrategy()
        assert await strategy.is_logged_in(page) is False


class TestLogin:
    async def test_login_success_path(self) -> None:
        page = AsyncMock()
        wait_calls: list[str] = []

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            _ = timeout_ms
            wait_calls.append(selector)
            if selector == sel.LOGIN_EMAIL:
                return
            if selector == sel.USER_MENU and len(wait_calls) > 1:
                return
            raise TimeoutError("not yet")

        page.wait_for_selector.side_effect = _wait
        strategy = DeezerStrategy()
        await strategy.login(page, _account())
        page.fill.assert_any_await(sel.LOGIN_EMAIL, "user@deezer.com")
        page.fill.assert_any_await(sel.LOGIN_PASSWORD, "hunter2")
        page.click.assert_awaited_with(sel.LOGIN_SUBMIT)
        assert sel.USER_MENU in wait_calls

    async def test_login_form_missing_raises_target_site_error(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no form")
        strategy = DeezerStrategy()
        with pytest.raises(TargetSiteError, match="login form"):
            await strategy.login(page, _account())

    async def test_login_credentials_rejected_raises_auth_error(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            _ = timeout_ms
            if selector == sel.LOGIN_EMAIL:
                return
            if selector == sel.LOGIN_ERROR:
                return
            raise TimeoutError("nada")

        page.wait_for_selector.side_effect = _wait
        strategy = DeezerStrategy()
        with pytest.raises(AuthenticationError, match="credenciales"):
            await strategy.login(page, _account())

    async def test_login_with_hcaptcha_uses_solver(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = "site-key-abc"
        captcha_seen = {"hcaptcha": False}

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            _ = timeout_ms
            if selector == sel.LOGIN_EMAIL:
                return
            if selector == sel.HCAPTCHA_CONTAINER and not captcha_seen["hcaptcha"]:
                captcha_seen["hcaptcha"] = True
                return
            if selector == sel.USER_MENU:
                return
            raise TimeoutError("nope")

        page.wait_for_selector.side_effect = _wait

        solver = AsyncMock()
        solver.solve_hcaptcha.return_value = "captcha-token-xyz"
        strategy = DeezerStrategy(captcha_solver=solver)
        await strategy.login(page, _account())
        solver.solve_hcaptcha.assert_awaited_once()
        # Verificamos que pasamos site_key recuperado del DOM.
        kwargs = solver.solve_hcaptcha.await_args.kwargs
        assert kwargs["site_key"] == "site-key-abc"

    async def test_login_with_hcaptcha_no_solver_raises(self) -> None:
        page = AsyncMock()

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            _ = timeout_ms
            if selector == sel.LOGIN_EMAIL:
                return
            if selector == sel.HCAPTCHA_CONTAINER:
                return
            raise TimeoutError("no aun")

        page.wait_for_selector.side_effect = _wait
        strategy = DeezerStrategy()
        with pytest.raises(AuthenticationError, match="hCaptcha"):
            await strategy.login(page, _account())


class TestPerformAction:
    async def test_perform_action_clicks_play_pause_twice_with_replay(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        strategy = DeezerStrategy()
        await strategy.perform_action(page, "https://www.deezer.com/track/1234", 35)
        page.goto.assert_awaited_with(
            "https://www.deezer.com/track/1234",
            wait_until="domcontentloaded",
        )
        # Dos clicks: play inicial + replay.
        assert page.click.await_count == 2
        page.click.assert_any_await(sel.PLAY_PAUSE)

    async def test_perform_action_raises_when_player_missing(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("sin player")
        strategy = DeezerStrategy()
        with pytest.raises(TargetSiteError, match="player Deezer"):
            await strategy.perform_action(page, "https://x", 35)


class TestPlayPlannedSession:
    async def test_walks_plan_and_clicks_play_for_each_track(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.return_value = None
        plan = PlannedSession(
            target_track_uri="deezer:track:1001",
            plays=(
                PlannedTrackPlay(
                    track_uri="deezer:track:300",
                    artist_uri="deezer:artist:50",
                    listen_seconds=180,
                    pre_jitter_seconds=4,
                    is_target=False,
                    is_replay=False,
                ),
                PlannedTrackPlay(
                    track_uri="deezer:track:1001",
                    artist_uri="deezer:artist:42",
                    listen_seconds=210,
                    pre_jitter_seconds=8,
                    is_target=True,
                    is_replay=False,
                ),
                PlannedTrackPlay(
                    track_uri="deezer:track:1001",
                    artist_uri="deezer:artist:42",
                    listen_seconds=210,
                    pre_jitter_seconds=10,
                    is_target=True,
                    is_replay=True,
                ),
            ),
        )
        strategy = DeezerStrategy()
        await strategy.play_planned_session(page, plan)
        # 3 navegaciones a 3 tracks distintos (uno repetido como replay).
        assert page.goto.await_count == 3
        # Cada navegacion debe ir a una URL deezer/track/<id>.
        urls = [call.args[0] for call in page.goto.await_args_list]
        assert urls == [
            "https://www.deezer.com/track/300",
            "https://www.deezer.com/track/1001",
            "https://www.deezer.com/track/1001",
        ]
        assert page.click.await_count == 3

    async def test_play_continues_when_one_track_fails(self) -> None:
        page = AsyncMock()
        call_count = {"n": 0}

        async def _wait(selector: str, *, timeout_ms: int = 30_000) -> None:
            _ = (selector, timeout_ms)
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise TimeoutError("falla puntual")

        page.wait_for_selector.side_effect = _wait
        plan = PlannedSession(
            target_track_uri="deezer:track:1001",
            plays=(
                PlannedTrackPlay(
                    track_uri="deezer:track:1001",
                    artist_uri="deezer:artist:42",
                    listen_seconds=180,
                    pre_jitter_seconds=3,
                    is_target=True,
                    is_replay=False,
                ),
                PlannedTrackPlay(
                    track_uri="deezer:track:300",
                    artist_uri="deezer:artist:50",
                    listen_seconds=200,
                    pre_jitter_seconds=4,
                    is_target=False,
                    is_replay=False,
                ),
            ),
        )
        strategy = DeezerStrategy()
        await strategy.play_planned_session(page, plan)
        # Goto se intenta 2 veces; click solo 1 (segundo track).
        assert page.goto.await_count == 2
        assert page.click.await_count == 1


class TestHelpers:
    async def test_get_current_track_uri_returns_namespaced_id(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = "1234"
        strategy = DeezerStrategy()
        assert await strategy.get_current_track_uri(page) == "deezer:track:1234"

    async def test_get_current_track_uri_returns_none_on_failure(self) -> None:
        page = AsyncMock()
        page.evaluate.side_effect = RuntimeError("boom")
        strategy = DeezerStrategy()
        assert await strategy.get_current_track_uri(page) is None

    async def test_get_current_artist_uri_returns_namespaced_id(self) -> None:
        page = AsyncMock()
        page.evaluate.return_value = "42"
        strategy = DeezerStrategy()
        assert await strategy.get_current_artist_uri(page) == "deezer:artist:42"

    async def test_wait_for_player_ready_raises_on_missing_widget(self) -> None:
        page = AsyncMock()
        page.wait_for_selector.side_effect = TimeoutError("no widget")
        strategy = DeezerStrategy()
        with pytest.raises(TargetSiteError, match="player no llego"):
            await strategy.wait_for_player_ready(page)
