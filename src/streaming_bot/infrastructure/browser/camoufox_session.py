"""Sesión de browser que envuelve `playwright.async_api.Page` con primitivas humanas.

Implementa `IRichBrowserSession` (que extiende `IBrowserSession`) componiendo:
- bezier_mouse para trayectorias.
- human_typing para delays/typos.
- emulación de visibilitychange para tab blur.
- queries DOM, screenshots, storage_state.

Toda la aleatoriedad usa un `Random` inyectado para que los tests sean estables.
"""

from __future__ import annotations

import asyncio
from random import Random
from typing import Any

from playwright.async_api import (
    BrowserContext,
    Page,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)
from structlog.stdlib import BoundLogger

from streaming_bot.domain.exceptions import BrowserCrashError, TargetSiteError
from streaming_bot.domain.persona import MouseProfile, TypingProfile
from streaming_bot.domain.ports.browser_rich import IRichBrowserSession
from streaming_bot.infrastructure.browser.bezier_mouse import (
    apply_velocity_jitter,
    bezier_curve,
    compute_overshoot,
)
from streaming_bot.infrastructure.browser.human_typing import (
    compute_keystroke_delays,
    inject_typos,
)


class CamoufoxSession(IRichBrowserSession):
    """Wrapper rich sobre `Page` lanzado por `CamoufoxDriver`."""

    def __init__(
        self,
        page: Page,
        context: BrowserContext,
        *,
        default_timeout_ms: int,
        mouse_profile: MouseProfile,
        typing_profile: TypingProfile,
        logger: BoundLogger,
        rng: Random | None = None,
    ) -> None:
        self._page = page
        self._context = context
        self._mouse = mouse_profile
        self._typing = typing_profile
        self._log = logger
        self._rng = rng if rng is not None else Random()  # noqa: S311
        # Estado del cursor virtual (Playwright no expone la posición real).
        viewport = page.viewport_size
        self._cursor_x: float = float(viewport["width"]) / 2.0 if viewport else 683.0
        self._cursor_y: float = float(viewport["height"]) / 2.0 if viewport else 384.0
        self._page.set_default_timeout(default_timeout_ms)

    # ────────────────────────────────────────────────────────────────────────
    # IBrowserSession (compat con el código actual)
    # ────────────────────────────────────────────────────────────────────────
    async def goto(self, url: str, *, wait_until: str = "networkidle") -> None:
        try:
            await self._page.goto(url, wait_until=wait_until)  # type: ignore[arg-type]
        except PlaywrightTimeoutError as exc:
            raise TargetSiteError(f"timeout navegando a {url}") from exc
        except PlaywrightError as exc:
            raise BrowserCrashError(str(exc)) from exc

    async def fill(self, selector: str, value: str) -> None:
        await self._page.fill(selector, value)

    async def click(self, selector: str) -> None:
        await self._page.click(selector)

    async def wait_for_selector(self, selector: str, *, timeout_ms: int = 30_000) -> None:
        try:
            await self._page.wait_for_selector(selector, timeout=timeout_ms)
        except PlaywrightTimeoutError as exc:
            raise TargetSiteError(f"selector no encontrado: {selector}") from exc

    async def evaluate(self, expression: str) -> Any:
        return await self._page.evaluate(expression)

    async def screenshot(self, path: str) -> None:
        await self._page.screenshot(path=path, full_page=True)

    async def content(self) -> str:
        return await self._page.content()

    async def storage_state(self) -> dict[str, Any]:
        state = await self._context.storage_state()
        return dict(state)

    # ────────────────────────────────────────────────────────────────────────
    # IRichBrowserSession - navegación extra
    # ────────────────────────────────────────────────────────────────────────
    async def go_back(self) -> None:
        await self._page.go_back()
        await asyncio.sleep(self._rng.uniform(0.3, 0.9))

    async def go_forward(self) -> None:
        await self._page.go_forward()
        await asyncio.sleep(self._rng.uniform(0.3, 0.9))

    async def reload(self) -> None:
        await self._page.reload()

    async def current_url(self) -> str:
        return self._page.url

    # ────────────────────────────────────────────────────────────────────────
    # IRichBrowserSession - mouse humano
    # ────────────────────────────────────────────────────────────────────────
    async def human_mouse_move(
        self,
        x: int,
        y: int,
        *,
        duration_ms: int = 500,
        bezier_steps: int = 30,
    ) -> None:
        """Mueve el cursor con curva Bezier hasta (x, y)."""
        start = (self._cursor_x, self._cursor_y)
        end = (float(x), float(y))
        curve = bezier_curve(
            start,
            end,
            control_points=self._mouse.bezier_control_points,
            steps=max(2, bezier_steps),
            rng=self._rng,
        )
        # Distribuye el `duration_ms` de forma proporcional al delay jitter.
        base_delay = max(1.0, duration_ms / max(1, bezier_steps))
        timed = apply_velocity_jitter(
            curve,
            stddev=self._mouse.velocity_stddev,
            base_delay_ms=base_delay,
            rng=self._rng,
        )
        for px, py, delay_ms in timed:
            await self._page.mouse.move(px, py)
            await asyncio.sleep(delay_ms / 1000.0)
        self._cursor_x, self._cursor_y = end

    async def hover(self, selector: str, *, duration_ms: int = 200) -> None:
        bbox = await self.get_bounding_box(selector)
        if bbox is None:
            raise TargetSiteError(f"no se pudo localizar selector para hover: {selector}")
        target_x = bbox[0] + bbox[2] / 2.0
        target_y = bbox[1] + bbox[3] / 2.0
        await self.human_mouse_move(int(target_x), int(target_y))
        await asyncio.sleep(duration_ms / 1000.0)

    async def human_click(
        self,
        selector: str,
        *,
        button: str = "left",
        click_count: int = 1,
        delay_ms_before: int = 0,
        offset_jitter_px: int = 5,
    ) -> None:
        """Click humano: Bezier → hover → overshoot opcional → click."""
        if delay_ms_before > 0:
            await asyncio.sleep(delay_ms_before / 1000.0)

        bbox = await self.get_bounding_box(selector)
        if bbox is None:
            raise TargetSiteError(f"no se pudo localizar selector para click: {selector}")

        bx, by, bw, bh = bbox
        # Punto target dentro del bounding box, con jitter respecto al centro.
        target_x = bx + bw / 2.0 + self._rng.uniform(-offset_jitter_px, offset_jitter_px)
        target_y = by + bh / 2.0 + self._rng.uniform(-offset_jitter_px, offset_jitter_px)
        # Ajusta target a los límites del bbox por si jitter > tamaño elemento.
        target_x = max(bx + 1.0, min(bx + bw - 1.0, target_x))
        target_y = max(by + 1.0, min(by + bh - 1.0, target_y))

        # Overshoot probabilístico.
        if self._rng.random() < self._mouse.overshoot_probability:
            overshoot = compute_overshoot(
                (target_x, target_y),
                max_pixels=self._mouse.overshoot_pixels_max,
                rng=self._rng,
            )
            await self.human_mouse_move(int(overshoot[0]), int(overshoot[1]))
            # Pequeña pausa antes de corregir.
            await asyncio.sleep(self._rng.uniform(0.04, 0.12))

        await self.human_mouse_move(int(target_x), int(target_y))

        # Pre-click hover (lectura del elemento).
        hover_ms = self._rng.randint(
            self._mouse.pre_click_hover_ms_min,
            self._mouse.pre_click_hover_ms_max,
        )
        await asyncio.sleep(hover_ms / 1000.0)

        # Click con delay variable entre press y release (más humano que 0ms).
        click_delay_ms = self._rng.randint(45, 120)
        await self._page.mouse.click(
            target_x,
            target_y,
            button=button,  # type: ignore[arg-type]
            click_count=click_count,
            delay=click_delay_ms,
        )

    # ────────────────────────────────────────────────────────────────────────
    # IRichBrowserSession - teclado humano
    # ────────────────────────────────────────────────────────────────────────
    async def human_type(
        self,
        selector: str,
        text: str,
        *,
        wpm: int = 70,
        wpm_stddev: int = 15,
        typo_probability: float = 0.03,
    ) -> None:
        """Tipea el texto char por char con delays + typos+correcciones."""
        # Foco en el campo. Evitamos el `human_click` aquí para no contaminar
        # las trayectorias del mouse en este flujo (Playwright `focus` directo).
        await self._page.focus(selector)

        # Override del profile con los parámetros explícitos pasados por el caller.
        profile = TypingProfile(
            avg_wpm=wpm,
            wpm_stddev=wpm_stddev,
            typo_probability_per_word=typo_probability,
            pause_probability_between_words=self._typing.pause_probability_between_words,
        )

        segments = inject_typos(text, probability_per_word=typo_probability, rng=self._rng)
        for chunk, is_typo in segments:
            delays = compute_keystroke_delays(chunk, profile=profile, rng=self._rng)
            for ch, delay_s in zip(chunk, delays, strict=True):
                await self._page.keyboard.type(ch)
                await asyncio.sleep(delay_s)
            if is_typo:
                # Corrige: backspace por cada carácter del chunk erróneo.
                for _ in range(len(chunk)):
                    await self._page.keyboard.press("Backspace")
                    await asyncio.sleep(self._rng.uniform(0.04, 0.10))

    async def press_key(self, key: str, *, count: int = 1, delay_ms: int = 80) -> None:
        for _ in range(count):
            await self._page.keyboard.press(key)
            await asyncio.sleep(delay_ms / 1000.0)

    async def human_press_key(self, key: str, *, modifiers: tuple[str, ...] = ()) -> None:
        """Presiona una tecla con modificadores (ej. Control+L)."""
        combo = "+".join((*modifiers, key)) if modifiers else key
        await self._page.keyboard.press(combo)

    # ────────────────────────────────────────────────────────────────────────
    # IRichBrowserSession - scroll humano
    # ────────────────────────────────────────────────────────────────────────
    async def human_scroll(
        self,
        *,
        direction: str = "down",
        pixels: int,
        duration_ms: int = 800,
    ) -> None:
        """Scroll con micro-steps (50-150px) y delays entre steps."""
        if pixels <= 0:
            return
        sign = 1 if direction == "down" else -1
        remaining = pixels
        # Total steps proporcional a la duración deseada.
        steps_count = max(4, duration_ms // 60)
        per_step_delay_ms = duration_ms / steps_count
        while remaining > 0:
            step = min(remaining, self._rng.randint(50, 150))
            await self._page.mouse.wheel(0, sign * step)
            jittered = max(20.0, per_step_delay_ms * self._rng.uniform(0.7, 1.3))
            await asyncio.sleep(jittered / 1000.0)
            remaining -= step

    async def human_drag(self, source_selector: str, target_selector: str) -> None:
        """Drag&drop humano: mueve, mousedown, mueve curva, mouseup."""
        source_bbox = await self.get_bounding_box(source_selector)
        target_bbox = await self.get_bounding_box(target_selector)
        if source_bbox is None or target_bbox is None:
            raise TargetSiteError("drag: source/target no localizados")
        sx = source_bbox[0] + source_bbox[2] / 2.0
        sy = source_bbox[1] + source_bbox[3] / 2.0
        tx = target_bbox[0] + target_bbox[2] / 2.0
        ty = target_bbox[1] + target_bbox[3] / 2.0
        await self.human_mouse_move(int(sx), int(sy))
        await self._page.mouse.down()
        await self.human_mouse_move(int(tx), int(ty))
        await asyncio.sleep(self._rng.uniform(0.10, 0.25))
        await self._page.mouse.up()

    # ────────────────────────────────────────────────────────────────────────
    # IRichBrowserSession - viewport y queries DOM
    # ────────────────────────────────────────────────────────────────────────
    async def get_viewport_size(self) -> tuple[int, int]:
        size = self._page.viewport_size
        if size is None:
            return (0, 0)
        return (int(size["width"]), int(size["height"]))

    async def set_viewport_size(self, width: int, height: int) -> None:
        await self._page.set_viewport_size({"width": width, "height": height})

    async def query_selector_count(self, selector: str) -> int:
        return await self._page.locator(selector).count()

    async def is_visible(self, selector: str, *, timeout_ms: int = 1000) -> bool:
        try:
            await self._page.wait_for_selector(selector, state="visible", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            return False
        return True

    async def get_text(self, selector: str) -> str:
        text = await self._page.locator(selector).first.text_content()
        return text or ""

    async def get_bounding_box(
        self,
        selector: str,
    ) -> tuple[float, float, float, float] | None:
        locator = self._page.locator(selector).first
        bbox = await locator.bounding_box()
        if bbox is None:
            return None
        return (float(bbox["x"]), float(bbox["y"]), float(bbox["width"]), float(bbox["height"]))

    # ────────────────────────────────────────────────────────────────────────
    # IRichBrowserSession - comportamiento de página
    # ────────────────────────────────────────────────────────────────────────
    async def emulate_tab_blur(self, *, duration_ms: int) -> None:
        """Dispara visibilitychange='hidden' por `duration_ms` y vuelve a 'visible'."""
        await self._page.evaluate(
            """() => {
                Object.defineProperty(document, 'visibilityState',
                    { value: 'hidden', writable: true, configurable: true });
                Object.defineProperty(document, 'hidden',
                    { value: true, writable: true, configurable: true });
                document.dispatchEvent(new Event('visibilitychange'));
            }"""
        )
        await asyncio.sleep(duration_ms / 1000.0)
        await self._page.evaluate(
            """() => {
                Object.defineProperty(document, 'visibilityState',
                    { value: 'visible', writable: true, configurable: true });
                Object.defineProperty(document, 'hidden',
                    { value: false, writable: true, configurable: true });
                document.dispatchEvent(new Event('visibilitychange'));
            }"""
        )

    async def wait(self, ms: int) -> None:
        await asyncio.sleep(ms / 1000.0)
