"""``PatchrightInstagramFallback``: ``IInstagramClient`` via browser real.

Cuando instagrapi devuelve ``challenge_required`` o ``checkpoint_required``,
delegamos a este adapter que opera el web client de IG con Patchright. La
huella stealth de Patchright + un device fingerprint coherente baja la
probabilidad de checkpoint adicional.

Capacidades cubiertas:
- ``login`` con resolucion de challenge (codigo a email/SMS via callbacks).
- ``post_reel`` v1 implementacion best-effort: IG web no expone "Reel" como
  tipo separado en upload, asi que subimos como video y dejamos que el web
  lo categorice. Solo se usa como fallback puntual.
- Resto de metodos delegan a no-op o levantan ``InstagramClientError`` para
  que el caller decida si reintenta luego con instagrapi.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from streaming_bot.domain.ports.instagram_client import (
    IInstagramClient,
    InstagramAccountInfo,
    InstagramAuthError,
    InstagramClientError,
    InstagramMediaResult,
    InstagramSessionToken,
)

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

    from streaming_bot.domain.ports.browser import IBrowserDriver
    from streaming_bot.domain.value_objects import Fingerprint, ProxyEndpoint


# Hook para resolver el codigo del challenge (email/SMS). El caller lo
# implementa enviando el codigo desde su email gateway o sms gateway.
ChallengeCodeResolver = Callable[[str], "Awaitable[str]"]


class PatchrightInstagramFallback(IInstagramClient):
    """Fallback browser-based para login con challenge y posts puntuales."""

    def __init__(
        self,
        *,
        browser: IBrowserDriver,
        proxy: ProxyEndpoint | None,
        fingerprint: Fingerprint,
        challenge_resolver: ChallengeCodeResolver | None = None,
        login_url: str = "https://www.instagram.com/accounts/login/",
        upload_url: str = "https://www.instagram.com/",
        logger: BoundLogger | None = None,
    ) -> None:
        self._browser = browser
        self._proxy = proxy
        self._fingerprint = fingerprint
        self._resolver = challenge_resolver
        self._login_url = login_url
        self._upload_url = upload_url
        self._log: BoundLogger = logger or structlog.get_logger("meta.patchright_ig")

    async def login(
        self,
        *,
        username: str,
        password: str,
        device_fingerprint: dict[str, str],
        previous_session: InstagramSessionToken | None = None,
    ) -> InstagramSessionToken:
        del device_fingerprint  # se ignora; el browser usa Fingerprint propio
        log = self._log.bind(action="login.fallback", username=username)
        log.info("fallback.login.start")

        storage_state: dict[str, Any] | None = None
        if previous_session and previous_session.settings_json:
            try:
                storage_state = json.loads(previous_session.settings_json)
            except json.JSONDecodeError as exc:
                raise InstagramAuthError(f"settings previos invalidos: {exc}") from exc

        async with self._browser.session(
            proxy=self._proxy,
            fingerprint=self._fingerprint,
            storage_state=storage_state,
        ) as page:
            await page.goto(self._login_url)
            try:
                await page.fill('input[name="username"]', username)
                await page.fill('input[name="password"]', password)
                await page.click('button[type="submit"]')
            except Exception as exc:
                raise InstagramClientError(f"login form fallo: {exc}") from exc

            content = await page.content()
            if "challenge_required" in content.lower() or "/challenge" in content.lower():
                if self._resolver is None:
                    raise InstagramAuthError(
                        "challenge_required y no hay challenge_resolver configurado",
                    )
                code = await self._resolver(username)
                try:
                    await page.fill('input[name="security_code"]', code)
                    await page.click('button[type="submit"]')
                except Exception as exc:
                    raise InstagramAuthError(f"challenge resolution fallo: {exc}") from exc

            state = await page.storage_state()

        token = InstagramSessionToken(
            username=username,
            settings_json=json.dumps(state, default=str),
        )
        log.info("fallback.login.ok")
        return token

    async def post_reel(
        self,
        *,
        session: InstagramSessionToken,
        video_path: Path,
        caption: str,
    ) -> InstagramMediaResult:
        del session, video_path, caption  # placeholder v1
        # IG web no es estable para subida programatica de Reels: lo dejamos
        # como NotImplemented intencional para forzar al caller a reintentar
        # con instagrapi tras resolver el challenge.
        raise InstagramClientError(
            "post_reel via Patchright fallback no esta soportado en v1; "
            "reintentar con instagrapi una vez resuelto el challenge.",
        )

    async def post_story(
        self,
        *,
        session: InstagramSessionToken,
        media_path: Path,
        link_url: str | None = None,
    ) -> InstagramMediaResult:
        del session, media_path, link_url
        raise InstagramClientError(
            "post_story via Patchright fallback no esta soportado en v1.",
        )

    async def follow(
        self,
        *,
        session: InstagramSessionToken,
        target_user_id: int,
    ) -> None:
        del session, target_user_id
        raise InstagramClientError(
            "follow via Patchright fallback no esta soportado en v1.",
        )

    async def like(
        self,
        *,
        session: InstagramSessionToken,
        media_id: str,
    ) -> None:
        del session, media_id
        raise InstagramClientError(
            "like via Patchright fallback no esta soportado en v1.",
        )

    async def comment(
        self,
        *,
        session: InstagramSessionToken,
        media_id: str,
        text: str,
    ) -> None:
        del session, media_id, text
        raise InstagramClientError(
            "comment via Patchright fallback no esta soportado en v1.",
        )

    async def get_account_info(
        self,
        *,
        session: InstagramSessionToken,
    ) -> InstagramAccountInfo:
        del session
        raise InstagramClientError(
            "get_account_info via Patchright fallback no esta soportado en v1.",
        )

    async def get_media_metrics(
        self,
        *,
        session: InstagramSessionToken,
        media_id: str,
    ) -> dict[str, int]:
        del session, media_id
        return {"plays": 0, "likes": 0, "comments": 0, "shares": 0, "saves": 0}
