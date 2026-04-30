"""Tests de CamoufoxSession con mocks de Playwright Page/Context.

No se inicia browser real; sólo verificamos que las primitivas humanas
disparan las llamadas correctas a `page.mouse.*` y `page.keyboard.*`.
"""

from __future__ import annotations

from random import Random
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from streaming_bot.domain.exceptions import TargetSiteError
from streaming_bot.domain.persona import MouseProfile, TypingProfile
from streaming_bot.infrastructure.browser.camoufox_session import CamoufoxSession

if TYPE_CHECKING:
    from collections.abc import Callable


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────
def _make_mock_page(*, viewport: tuple[int, int] = (1366, 768)) -> MagicMock:
    page = MagicMock()
    page.viewport_size = {"width": viewport[0], "height": viewport[1]}
    page.url = "https://example.test/"

    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.click = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.mouse.down = AsyncMock()
    page.mouse.up = AsyncMock()

    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()

    page.set_default_timeout = MagicMock()
    page.set_viewport_size = AsyncMock()
    page.focus = AsyncMock()
    page.evaluate = AsyncMock(return_value=None)
    page.go_back = AsyncMock()
    page.go_forward = AsyncMock()
    page.reload = AsyncMock()
    return page


def _make_locator(*, bbox: dict[str, float] | None, text: str = "") -> MagicMock:
    locator = MagicMock()
    locator.first = locator  # `.first` devuelve self para encadenar.
    locator.bounding_box = AsyncMock(return_value=bbox)
    locator.text_content = AsyncMock(return_value=text)
    locator.count = AsyncMock(return_value=1)
    return locator


def _make_context() -> MagicMock:
    ctx = MagicMock()
    ctx.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    return ctx


def _make_session(
    page: MagicMock,
    *,
    rng_seed: int = 0,
    mouse_profile: MouseProfile | None = None,
) -> CamoufoxSession:
    return CamoufoxSession(
        page,
        _make_context(),
        default_timeout_ms=10_000,
        mouse_profile=mouse_profile
        or MouseProfile(
            bezier_control_points=2,
            velocity_stddev=0.1,
            overshoot_probability=0.0,  # determinista
            pre_click_hover_ms_min=10,
            pre_click_hover_ms_max=10,
        ),
        typing_profile=TypingProfile(
            avg_wpm=600,  # rapidísimo para tests veloces
            pause_probability_between_words=0.0,
            typo_probability_per_word=0.0,
        ),
        logger=structlog.get_logger(),
        rng=Random(rng_seed),
    )


@pytest.fixture
def fast_sleep(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Reemplaza asyncio.sleep por una versión instantánea para acelerar tests."""

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(
        "streaming_bot.infrastructure.browser.camoufox_session.asyncio.sleep",
        _no_sleep,
    )
    return _no_sleep


# ────────────────────────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────────────────────────
class TestHumanClick:
    async def test_human_click_calls_mouse_move_many_times_then_click(
        self,
        fast_sleep: Callable[..., None],
    ) -> None:
        page = _make_mock_page()
        page.locator = MagicMock(
            return_value=_make_locator(bbox={"x": 100, "y": 200, "width": 50, "height": 30})
        )
        session = _make_session(page)

        await session.human_click("button#play")

        # human_mouse_move usa bezier_steps=30 por defecto → ≥30 movimientos.
        assert page.mouse.move.await_count >= 25
        # Y un click final con delay > 0.
        page.mouse.click.assert_awaited_once()
        kwargs = page.mouse.click.call_args.kwargs
        assert kwargs["button"] == "left"
        assert kwargs["click_count"] == 1
        assert kwargs["delay"] >= 1

    async def test_human_click_overshoot_triggers_extra_moves(
        self,
        fast_sleep: Callable[..., None],
    ) -> None:
        # overshoot_probability=1.0 → siempre overshoot+correct.
        page = _make_mock_page()
        page.locator = MagicMock(
            return_value=_make_locator(bbox={"x": 100, "y": 200, "width": 50, "height": 30})
        )
        profile = MouseProfile(
            bezier_control_points=2,
            velocity_stddev=0.1,
            overshoot_probability=1.0,
            overshoot_pixels_max=20,
            pre_click_hover_ms_min=5,
            pre_click_hover_ms_max=5,
        )
        session = _make_session(page, mouse_profile=profile)

        await session.human_click("button#play")
        # Con overshoot debe haber dos invocaciones a human_mouse_move ⇒ ≥ 2*30 moves.
        assert page.mouse.move.await_count >= 50

    async def test_human_click_raises_when_selector_missing(
        self,
        fast_sleep: Callable[..., None],
    ) -> None:
        page = _make_mock_page()
        page.locator = MagicMock(return_value=_make_locator(bbox=None))
        session = _make_session(page)

        with pytest.raises(TargetSiteError):
            await session.human_click("button#missing")


class TestHumanType:
    async def test_human_type_writes_each_character(
        self,
        fast_sleep: Callable[..., None],
    ) -> None:
        page = _make_mock_page()
        session = _make_session(page)

        await session.human_type("input#search", "hola")

        # 4 chars (sin typos por probability=0.0).
        assert page.keyboard.type.await_count == 4
        # focus se llamó en el campo.
        page.focus.assert_awaited_once_with("input#search")

    async def test_human_type_with_typos_invokes_backspace(
        self,
        fast_sleep: Callable[..., None],
    ) -> None:
        page = _make_mock_page()
        # Forzamos typos altos para activar el path de corrección.
        session = CamoufoxSession(
            page,
            _make_context(),
            default_timeout_ms=10_000,
            mouse_profile=MouseProfile(),
            typing_profile=TypingProfile(avg_wpm=600),
            logger=structlog.get_logger(),
            rng=Random(0),
        )

        await session.human_type("input#search", "buenosdias", typo_probability=1.0)

        # Al menos 1 backspace por la corrección del typo.
        backspaces = [
            c for c in page.keyboard.press.await_args_list if c.args and c.args[0] == "Backspace"
        ]
        assert len(backspaces) >= 1


class TestViewportAndQueries:
    async def test_get_viewport_size_returns_page_viewport(
        self,
        fast_sleep: Callable[..., None],
    ) -> None:
        page = _make_mock_page(viewport=(1280, 720))
        session = _make_session(page)
        assert await session.get_viewport_size() == (1280, 720)

    async def test_query_selector_count_uses_locator(
        self,
        fast_sleep: Callable[..., None],
    ) -> None:
        page = _make_mock_page()
        page.locator = MagicMock(return_value=_make_locator(bbox=None))
        session = _make_session(page)
        assert await session.query_selector_count("li.song") == 1


class TestTabBlur:
    async def test_emulate_tab_blur_dispatches_visibility_events(
        self,
        fast_sleep: Callable[..., None],
    ) -> None:
        page = _make_mock_page()
        session = _make_session(page)

        await session.emulate_tab_blur(duration_ms=10)

        # 2 evaluaciones: hidden y visible.
        assert page.evaluate.await_count == 2
        # El primer script debe contener 'hidden' y el segundo 'visible'.
        first_script = page.evaluate.await_args_list[0].args[0]
        second_script = page.evaluate.await_args_list[1].args[0]
        assert "hidden" in first_script
        assert "visible" in second_script


class TestNavigation:
    async def test_go_back_invokes_page_go_back(
        self,
        fast_sleep: Callable[..., None],
    ) -> None:
        page = _make_mock_page()
        session = _make_session(page)
        await session.go_back()
        page.go_back.assert_awaited_once()

    async def test_current_url_returns_page_url(
        self,
        fast_sleep: Callable[..., None],
    ) -> None:
        page = _make_mock_page()
        page.url = "https://spotify.com/home"
        session = _make_session(page)
        assert await session.current_url() == "https://spotify.com/home"
