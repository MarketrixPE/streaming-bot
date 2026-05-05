"""Estrategia Spotify Web Player V2 con behavioral engine v2.

Sucesora del `SpotifyWebPlayerStrategy` legacy (que se mantiene intacto
por backward compat). Esta version integra el stack 2026:

- Ghost-cursor (`application.behavior.ghost_cursor`) para clicks con
  curva Bezier + overshoot opcional + micro-pausa hover.
- Decision delays (`application.behavior.decision_delay`) que insertan
  pausas log-normal moduladas por engagement_level y hora local antes
  de cada accion.
- `RatioController` (opcional) que decide cual save/skip/queue/like
  ejecutar a continuacion respetando los targets humanos por geo+genero.
- `ICaptchaSolver` (opcional) inyectado: si durante el login aparece un
  CAPTCHA (reCAPTCHA v2, hCaptcha, Turnstile), intenta resolverlo via
  el solver antes de fallar; si el solver tambien falla, eleva
  `AuthenticationError`.

Selectores Q1 2026 viven en `spotify_selectors.py` con fallbacks por
estabilidad (data-testid > aria-label > name=...).

La sesion del browser viene del `IRichBrowserDriver` (Patchright /
Camoufox / Mixed): la firma de los metodos heredados de `ISiteStrategy`
acepta `IBrowserSession` por compatibilidad de Liskov, pero internamente
casteamos a `IRichBrowserSession` para usar las primitivas humanas
(`human_click`, `human_type`, `get_bounding_box`).
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, cast

import structlog

from streaming_bot.application.behavior.decision_delay import (
    DecisionType,
    DelayContext,
)
from streaming_bot.application.ports import IRichSiteStrategy
from streaming_bot.application.strategies import BehaviorIntent
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.domain.ports.captcha_solver import CaptchaSolverError
from streaming_bot.presentation.strategies.spotify_selectors import (
    HOME_URL,
    LOGIN_URL,
    SpotifySelectors,
    pick_visible_async,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from structlog.stdlib import BoundLogger

    from streaming_bot.application.behavior.decision_delay import (
        DecisionDelayPolicy,
    )
    from streaming_bot.application.behavior.ghost_cursor import GhostCursorEngine
    from streaming_bot.application.strategies import RatioController
    from streaming_bot.domain.entities import Account
    from streaming_bot.domain.persona import Persona
    from streaming_bot.domain.ports.browser import IBrowserSession
    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession
    from streaming_bot.domain.ports.captcha_solver import ICaptchaSolver


# Polling de login: 40 iteraciones x 0.5s = 20s, mismo orden que el legacy.
_LOGIN_POLL_INTERVAL_SECONDS = 0.5
_LOGIN_POLL_ATTEMPTS = 40

# Listen minimo Spotify para contar como stream valido (se replica del legacy).
_MIN_LISTEN_SECONDS = 35


class SpotifyWebPlayerStrategyV2(IRichSiteStrategy):
    """Estrategia v2 de Spotify Web Player.

    Esta clase es composicion: el comportamiento humano fino (los 33+
    behaviors granulares) sigue viviendo en `HumanBehaviorEngine`. Esta
    estrategia se ocupa solo de la "membrana" entre el use case y el
    sitio: login, deteccion de logueado, navegacion al player, lectura
    de URI actual, y decision de la proxima intent global (delegada al
    RatioController para mantener tasas humanas).
    """

    def __init__(
        self,
        *,
        selectors: SpotifySelectors | None = None,
        captcha_solver: ICaptchaSolver | None = None,
        cursor: GhostCursorEngine | None = None,
        delay_policy: DecisionDelayPolicy | None = None,
        ratio_controller: RatioController | None = None,
        logger: BoundLogger | None = None,
    ) -> None:
        self._selectors = selectors or SpotifySelectors.default()
        self._captcha = captcha_solver
        self._cursor = cursor
        self._delays = delay_policy
        self._ratio = ratio_controller
        self._log = logger or structlog.get_logger("spotify_v2")
        # Posicion del cursor que mantenemos para el ghost-cursor (origin de
        # la siguiente trayectoria). Se inicializa en (0, 0) y se actualiza
        # tras cada human-click via bbox.
        self._cursor_pos: tuple[float, float] = (0.0, 0.0)

    # ── Propiedades de inspeccion ─────────────────────────────────────────
    @property
    def selectors(self) -> SpotifySelectors:
        return self._selectors

    @property
    def ratio_controller(self) -> RatioController | None:
        return self._ratio

    # ── ISiteStrategy: is_logged_in ───────────────────────────────────────
    async def is_logged_in(self, page: IBrowserSession) -> bool:
        rich = cast("IRichBrowserSession", page)
        selector = await pick_visible_async(
            rich,
            self._selectors.user_widget,
            timeout_ms=3_000,
        )
        return selector is not None

    # ── ISiteStrategy: login ──────────────────────────────────────────────
    async def login(self, page: IBrowserSession, account: Account) -> None:
        """Login con decision delays + ghost cursor + captcha solver opcional.

        Flujo:
        1. Navegar a `accounts.spotify.com/login`.
        2. Esperar el form; si no aparece, `TargetSiteError` (transient).
        3. Tipear username y password con humano + decision delay.
        4. Click submit.
        5. Polling 20s esperando `user_widget`. Si aparece captcha y hay
           solver, resolver. Si aparece login_error, `AuthenticationError`.
        6. Timeout final -> `AuthenticationError`.
        """
        rich = cast("IRichBrowserSession", page)
        await rich.goto(LOGIN_URL, wait_until="domcontentloaded")

        username_sel = await pick_visible_async(
            rich,
            self._selectors.login_username,
            timeout_ms=10_000,
        )
        if username_sel is None:
            raise TargetSiteError("login form no aparecio (selectores Q1 2026)")

        await self._wait_decision(DecisionType.TYPE)
        await self._human_fill(rich, username_sel, account.username)

        password_sel = await pick_visible_async(
            rich,
            self._selectors.login_password,
            timeout_ms=2_000,
        )
        if password_sel is None:
            raise TargetSiteError("password input no aparecio (Q1 2026 fallbacks agotados)")

        await self._wait_decision(DecisionType.TYPE)
        await self._human_fill(rich, password_sel, account.password)

        button_sel = await pick_visible_async(
            rich,
            self._selectors.login_button,
            timeout_ms=2_000,
        )
        if button_sel is None:
            raise TargetSiteError("submit button no aparecio (Q1 2026 fallbacks agotados)")

        await self._wait_decision(DecisionType.CLICK)
        await self._human_click(rich, button_sel)

        await self._await_login_outcome(rich)

    # ── ISiteStrategy: perform_action ─────────────────────────────────────
    async def perform_action(
        self,
        page: IBrowserSession,
        target_url: str,
        listen_seconds: int,
    ) -> None:
        """Reproduccion simple (modo compat con StreamSongUseCase legacy).

        El flujo rico (playlist + behaviors) se invoca via
        `PlaylistSessionUseCase`; aqui solo iniciamos un play y
        sleepeamos `listen_seconds` (con piso de 35s para que cuente).
        """
        rich = cast("IRichBrowserSession", page)
        await rich.goto(target_url, wait_until="domcontentloaded")

        play_sel = await pick_visible_async(
            rich,
            self._selectors.play_button,
            timeout_ms=10_000,
        )
        if play_sel is not None:
            await self._human_click(rich, play_sel)
        else:
            fallback = await pick_visible_async(
                rich,
                self._selectors.play_pause,
                timeout_ms=5_000,
            )
            if fallback is None:
                raise TargetSiteError("no se pudo iniciar reproduccion")
            await self._human_click(rich, fallback)

        await asyncio.sleep(max(listen_seconds, _MIN_LISTEN_SECONDS))

    # ── IRichSiteStrategy: helpers de player ──────────────────────────────
    async def wait_for_player_ready(self, page: IRichBrowserSession) -> None:
        widget_sel = await pick_visible_async(
            page,
            self._selectors.now_playing_widget,
            timeout_ms=15_000,
        )
        if widget_sel is None:
            raise TargetSiteError("player no llego a estado ready (now_playing_widget)")
        title_sel = await pick_visible_async(
            page,
            self._selectors.track_title,
            timeout_ms=10_000,
        )
        if title_sel is None:
            raise TargetSiteError("player no llego a estado ready (track_title)")

    async def get_current_track_uri(self, page: IRichBrowserSession) -> str | None:
        try:
            uri = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('[data-testid=\"now-playing-widget\"]');"
                "  return el && el.getAttribute('data-track-uri');"
                "}",
            )
        except Exception:
            return None
        return str(uri) if uri else None

    async def get_current_artist_uri(self, page: IRichBrowserSession) -> str | None:
        try:
            href = await page.evaluate(
                "() => {"
                "  const el = document.querySelector("
                "    '[data-testid=\"context-item-info-artist\"]'"
                "  );"
                "  return el && el.getAttribute('href');"
                "}",
            )
        except Exception:
            return None
        if not href:
            return None
        artist_id = str(href).rstrip("/").split("/")[-1]
        return f"spotify:artist:{artist_id}" if artist_id else None

    # ── Extension v2: decision de proxima intent ──────────────────────────
    def next_intent(
        self,
        *,
        persona: Persona,
        recent_history: Sequence[BehaviorIntent] = (),
    ) -> BehaviorIntent:
        """Delegacion al `RatioController` (NONE si no esta inyectado).

        El use case (PlaylistSessionUseCase) puede consultar este metodo
        track-a-track antes de ejecutar la bateria de behaviors para
        mantener el ratio agregado dentro del rango humano por geo+genero.
        """
        if self._ratio is None:
            return BehaviorIntent.NONE
        return self._ratio.next_action(persona=persona, recent_history=recent_history)

    # ── Helpers internos ──────────────────────────────────────────────────
    async def _await_login_outcome(self, page: IRichBrowserSession) -> None:
        """Polling del resultado del login con manejo de captcha y errores."""
        for _ in range(_LOGIN_POLL_ATTEMPTS):
            await asyncio.sleep(_LOGIN_POLL_INTERVAL_SECONDS)
            if await self._is_logged_in_quick(page):
                return
            if await self._captcha_present(page):
                await self._handle_captcha(page)
                # Tras un solve exitoso volvemos al loop, dando tiempo a que
                # Spotify procese la verificacion y emita user_widget.
                continue
            if await self._login_error_present(page):
                raise AuthenticationError("credenciales rechazadas (login_error_hint)")
        raise AuthenticationError("login no se completo en el tiempo esperado")

    async def _is_logged_in_quick(self, page: IRichBrowserSession) -> bool:
        selector = await pick_visible_async(
            page,
            self._selectors.user_widget,
            timeout_ms=300,
        )
        return selector is not None

    async def _captcha_present(self, page: IRichBrowserSession) -> bool:
        for group in (
            self._selectors.captcha_container,
            self._selectors.recaptcha_iframe,
            self._selectors.hcaptcha_iframe,
            self._selectors.turnstile_iframe,
        ):
            if await pick_visible_async(page, group, timeout_ms=200) is not None:
                return True
        return False

    async def _login_error_present(self, page: IRichBrowserSession) -> bool:
        selector = await pick_visible_async(
            page,
            self._selectors.login_error_hint,
            timeout_ms=200,
        )
        return selector is not None

    async def _handle_captcha(self, page: IRichBrowserSession) -> None:
        """Resuelve el captcha visible o eleva `AuthenticationError`."""
        if self._captcha is None:
            raise AuthenticationError("captcha durante login (sin captcha_solver inyectado)")
        try:
            solved = await self._attempt_captcha_solve(page)
        except CaptchaSolverError as exc:
            raise AuthenticationError(f"captcha solver fallo: {exc}") from exc
        if not solved:
            raise AuthenticationError("captcha solver no pudo resolver")

    async def _attempt_captcha_solve(self, page: IRichBrowserSession) -> bool:
        """Detecta el tipo de captcha, lo resuelve via solver e inyecta el token.

        Retorna False si el captcha es de un tipo no reconocido (no es un
        error: el caller lo trata como `AuthenticationError`).
        """
        if self._captcha is None:  # defensivo: _handle_captcha ya valida
            return False
        kind = await self._detect_captcha_kind(page)
        if kind is None:
            return False
        sitekey = await self._read_sitekey(page)
        page_url = await page.current_url()
        token: str
        injected_field: str
        if kind == "recaptcha" and sitekey is not None:
            token = await self._captcha.solve_recaptcha_v2(
                site_key=sitekey,
                page_url=page_url,
            )
            injected_field = "g-recaptcha-response"
        elif kind == "hcaptcha" and sitekey is not None:
            token = await self._captcha.solve_hcaptcha(
                site_key=sitekey,
                page_url=page_url,
            )
            injected_field = "h-captcha-response"
        elif kind == "turnstile" and sitekey is not None:
            token = await self._captcha.solve_cloudflare_turnstile(
                site_key=sitekey,
                page_url=page_url,
            )
            injected_field = "cf-turnstile-response"
        else:
            self._log.warning(
                "spotify_v2.captcha_unknown_or_no_sitekey",
                kind=kind,
                has_sitekey=sitekey is not None,
            )
            return False

        await self._inject_captcha_token(page, injected_field, token)
        # Reintentamos el submit (Spotify suele auto-validar v3 invisible,
        # pero v2 explicito requiere clic explicito).
        button_sel = await pick_visible_async(
            page,
            self._selectors.login_button,
            timeout_ms=1_000,
        )
        if button_sel is not None:
            with suppress(Exception):
                await page.click(button_sel)
        return True

    async def _detect_captcha_kind(self, page: IRichBrowserSession) -> str | None:
        """Identifica el tipo de captcha presente en orden de probabilidad."""
        if await pick_visible_async(
            page,
            self._selectors.recaptcha_iframe,
            timeout_ms=200,
        ) is not None:
            return "recaptcha"
        if await pick_visible_async(
            page,
            self._selectors.hcaptcha_iframe,
            timeout_ms=200,
        ) is not None:
            return "hcaptcha"
        if await pick_visible_async(
            page,
            self._selectors.turnstile_iframe,
            timeout_ms=200,
        ) is not None:
            return "turnstile"
        return None

    async def _read_sitekey(self, page: IRichBrowserSession) -> str | None:
        """Lee el primer `data-sitekey` presente en la pagina (recaptcha,
        hcaptcha y turnstile lo exponen en su contenedor o iframe).
        """
        try:
            value = await page.evaluate(
                "() => {"
                "  const el = document.querySelector('[data-sitekey]');"
                "  return el && el.getAttribute('data-sitekey');"
                "}",
            )
        except Exception:
            return None
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    @staticmethod
    async def _inject_captcha_token(
        page: IRichBrowserSession,
        field: str,
        token: str,
    ) -> None:
        """Inyecta el token resuelto en el textarea hidden del captcha.

        Los providers crean `textarea[name="g-recaptcha-response"]` (idem
        para hCaptcha y Turnstile). Si no existe, lo creamos como input
        hidden dentro del primer form del documento; eso permite al backend
        recibir el token junto al submit.
        """
        # Sanitizamos el token: solo se acepta en el JS literal, no en SQL.
        # Aun asi limitamos a printable ASCII para evitar inyeccion via
        # caracteres de cierre de string.
        safe_token = "".join(c for c in token if c.isprintable() and c not in "\\\"\n\r")
        await page.evaluate(
            f"""() => {{
              const field = '{field}';
              const value = '{safe_token}';
              let el = document.querySelector(`textarea[name="${{field}}"]`);
              if (!el) {{
                el = document.createElement('textarea');
                el.name = field;
                el.style.display = 'none';
                const form = document.querySelector('form');
                if (form) form.appendChild(el);
                else document.body.appendChild(el);
              }}
              el.value = value;
            }}"""
        )

    async def _wait_decision(self, decision: DecisionType) -> None:
        """Aplica el decision delay si la politica esta inyectada."""
        if self._delays is None:
            return
        ms = await self._delays.decide(DelayContext(decision=decision))
        if ms <= 0:
            return
        await asyncio.sleep(ms / 1000.0)

    async def _human_fill(
        self,
        page: IRichBrowserSession,
        selector: str,
        value: str,
    ) -> None:
        """Tipea humano si la sesion expone `human_type`, fill basico si no.

        Los drivers Patchright/Camoufox/Mixed implementan `human_type`; en
        tests con AsyncMock la primitiva esta presente y devuelve None.
        Si el atributo no existe (ej. driver legacy), caemos a `fill`.
        """
        if hasattr(page, "human_type"):
            await page.human_type(selector, value)
        else:
            await page.fill(selector, value)

    async def _human_click(self, page: IRichBrowserSession, selector: str) -> None:
        """Click humano: usa ghost-cursor si esta inyectado y hay bbox."""
        if self._cursor is not None:
            bbox = await self._safe_bbox(page, selector)
            if bbox is not None:
                x, y, width, height = bbox
                target = (x + width / 2.0, y + height / 2.0)
                await self._cursor.click_at(
                    page,
                    origin=self._cursor_pos,
                    target=target,
                    selector=selector,
                )
                self._cursor_pos = target
                return
        if hasattr(page, "human_click"):
            await page.human_click(selector)
        else:
            await page.click(selector)

    @staticmethod
    async def _safe_bbox(
        page: IRichBrowserSession,
        selector: str,
    ) -> tuple[float, float, float, float] | None:
        """Lee el bbox sin lanzar; devuelve None si la primitiva falla."""
        try:
            return await page.get_bounding_box(selector)
        except Exception:
            return None

    # ── Navegacion auxiliar (reutilizable por tests / debug) ──────────────
    async def navigate_home(self, page: IRichBrowserSession) -> None:
        """Navega a la home del web player. Usado por flows manuales."""
        await page.goto(HOME_URL, wait_until="domcontentloaded")
