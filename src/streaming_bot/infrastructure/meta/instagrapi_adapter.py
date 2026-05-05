"""``InstagrapiAdapter``: implementacion ``IInstagramClient`` con instagrapi.

instagrapi (https://github.com/subzeroid/instagrapi) v2.4.4 envuelve la API
mobile privada de Instagram. Hacer las cosas bien:

- Persistir y reusar el ``Client.get_settings()`` (device fingerprint + uuids
  + cookies). Cambiar device entre sesiones dispara ``challenge_required``.
- Detectar errores tipicos:
    * ``ChallengeRequired`` -> InstagramChallengeRequired (delegar a Patchright).
    * ``LoginRequired`` -> InstagramAuthError.
    * Resto -> InstagramClientError.
- ``post_reel`` usa ``Client.clip_upload`` (Reels endpoint Q1 2026).
- Las llamadas son sync: las ejecutamos en un threadpool con ``asyncio.to_thread``
  para no bloquear el event loop.

Para tests: el constructor acepta un ``client_factory`` para inyectar un mock
de ``instagrapi.Client`` sin tocar la libreria real.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from streaming_bot.domain.ports.instagram_client import (
    IInstagramClient,
    InstagramAccountInfo,
    InstagramAuthError,
    InstagramChallengeRequired,
    InstagramClientError,
    InstagramMediaResult,
    InstagramSessionToken,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from structlog.stdlib import BoundLogger


# Tipos exportados por instagrapi que detectamos por nombre (importacion lazy
# para que el resto del codebase no requiera la extra `meta`).
_CHALLENGE_EXC_NAMES = frozenset({"ChallengeRequired", "RecaptchaChallengeForm"})
_AUTH_EXC_NAMES = frozenset(
    {"LoginRequired", "BadPassword", "TwoFactorRequired", "AccountSuspended"},
)


def _classify_instagrapi_exception(exc: BaseException) -> Exception:
    """Clasifica una excepcion de instagrapi por nombre de clase.

    Importar instagrapi solo cuando se necesite mantiene mypy/ruff felices y
    permite testear el adapter sin tener instagrapi instalada (los tests
    inyectan excepciones plain ``Exception`` con ``__class__.__name__`` simulado).
    """
    name = type(exc).__name__
    if name in _CHALLENGE_EXC_NAMES:
        return InstagramChallengeRequired(f"instagrapi {name}: {exc}")
    if name in _AUTH_EXC_NAMES:
        return InstagramAuthError(f"instagrapi {name}: {exc}")
    return InstagramClientError(f"instagrapi {name}: {exc}")


class InstagrapiAdapter(IInstagramClient):
    """Adapter ``IInstagramClient`` envolviendo ``instagrapi.Client``.

    El ``client_factory`` permite tests sin la libreria real. Por defecto
    intenta importar ``instagrapi.Client`` y construye una instancia nueva
    por sesion (los settings hacen la persistencia entre runs).
    """

    def __init__(
        self,
        *,
        client_factory: Callable[[], Any] | None = None,
        sessions_dir: Path | None = None,
        logger: BoundLogger | None = None,
    ) -> None:
        self._client_factory = client_factory or self._default_client_factory
        self._sessions_dir = sessions_dir
        self._log: BoundLogger = logger or structlog.get_logger("meta.instagrapi")

    @staticmethod
    def _default_client_factory() -> Any:  # pragma: no cover - integracion real
        try:
            from instagrapi import Client  # noqa: PLC0415 - extra opcional `meta`
        except ImportError as exc:
            raise InstagramClientError(
                "instagrapi no esta instalado. Anade `streaming-bot[meta]`.",
            ) from exc
        return Client()

    async def login(
        self,
        *,
        username: str,
        password: str,
        device_fingerprint: dict[str, str],
        previous_session: InstagramSessionToken | None = None,
    ) -> InstagramSessionToken:
        log = self._log.bind(action="login", username=username)
        client = self._client_factory()
        if previous_session and previous_session.settings_json:
            try:
                settings = json.loads(previous_session.settings_json)
            except json.JSONDecodeError as exc:
                raise InstagramAuthError(
                    f"settings previos invalidos: {exc}",
                ) from exc
            try:
                await asyncio.to_thread(client.set_settings, settings)
            except Exception as exc:
                raise _classify_instagrapi_exception(exc) from exc
            log.debug("login.settings_restored")
        elif device_fingerprint:
            try:
                await asyncio.to_thread(client.set_device, device_fingerprint)
            except Exception as exc:
                raise _classify_instagrapi_exception(exc) from exc
            log.debug("login.device_set")

        try:
            await asyncio.to_thread(client.login, username, password)
        except Exception as exc:
            raise _classify_instagrapi_exception(exc) from exc

        try:
            settings = await asyncio.to_thread(client.get_settings)
        except Exception as exc:
            raise _classify_instagrapi_exception(exc) from exc

        token = InstagramSessionToken(
            username=username,
            settings_json=json.dumps(settings, default=str),
        )
        log.info("login.ok")
        return token

    async def post_reel(
        self,
        *,
        session: InstagramSessionToken,
        video_path: Path,
        caption: str,
    ) -> InstagramMediaResult:
        log = self._log.bind(action="post_reel", username=session.username)
        if not video_path.exists():  # noqa: ASYNC240 - chequeo barato de existencia
            raise InstagramClientError(f"video_path no existe: {video_path}")

        client = await self._restore_client(session)

        try:
            media = await asyncio.to_thread(client.clip_upload, video_path, caption)
        except Exception as exc:
            raise _classify_instagrapi_exception(exc) from exc

        log.info("post_reel.ok", media_id=getattr(media, "pk", None))
        return InstagramMediaResult(
            media_id=str(getattr(media, "pk", "")),
            code=str(getattr(media, "code", "")),
            caption=caption,
        )

    async def post_story(
        self,
        *,
        session: InstagramSessionToken,
        media_path: Path,
        link_url: str | None = None,
    ) -> InstagramMediaResult:
        log = self._log.bind(action="post_story", username=session.username)
        if not media_path.exists():  # noqa: ASYNC240 - chequeo barato de existencia
            raise InstagramClientError(f"media_path no existe: {media_path}")

        client = await self._restore_client(session)

        try:
            if link_url:
                media = await asyncio.to_thread(
                    client.video_upload_to_story,
                    media_path,
                    "",
                    [{"webUri": link_url}],
                )
            else:
                media = await asyncio.to_thread(client.video_upload_to_story, media_path, "")
        except Exception as exc:
            raise _classify_instagrapi_exception(exc) from exc

        log.info("post_story.ok")
        return InstagramMediaResult(
            media_id=str(getattr(media, "pk", "")),
            code=str(getattr(media, "code", "")),
            caption="",
        )

    async def follow(
        self,
        *,
        session: InstagramSessionToken,
        target_user_id: int,
    ) -> None:
        client = await self._restore_client(session)
        try:
            await asyncio.to_thread(client.user_follow, target_user_id)
        except Exception as exc:
            raise _classify_instagrapi_exception(exc) from exc

    async def like(
        self,
        *,
        session: InstagramSessionToken,
        media_id: str,
    ) -> None:
        client = await self._restore_client(session)
        try:
            await asyncio.to_thread(client.media_like, media_id)
        except Exception as exc:
            raise _classify_instagrapi_exception(exc) from exc

    async def comment(
        self,
        *,
        session: InstagramSessionToken,
        media_id: str,
        text: str,
    ) -> None:
        client = await self._restore_client(session)
        try:
            await asyncio.to_thread(client.media_comment, media_id, text)
        except Exception as exc:
            raise _classify_instagrapi_exception(exc) from exc

    async def get_account_info(
        self,
        *,
        session: InstagramSessionToken,
    ) -> InstagramAccountInfo:
        client = await self._restore_client(session)
        try:
            info = await asyncio.to_thread(client.account_info)
        except Exception as exc:
            raise _classify_instagrapi_exception(exc) from exc

        return InstagramAccountInfo(
            username=str(getattr(info, "username", session.username)),
            user_id=int(getattr(info, "pk", 0)),
            follower_count=int(getattr(info, "follower_count", 0)),
            following_count=int(getattr(info, "following_count", 0)),
            media_count=int(getattr(info, "media_count", 0)),
            is_private=bool(getattr(info, "is_private", False)),
            is_verified=bool(getattr(info, "is_verified", False)),
        )

    async def get_media_metrics(
        self,
        *,
        session: InstagramSessionToken,
        media_id: str,
    ) -> dict[str, int]:
        client = await self._restore_client(session)
        try:
            info = await asyncio.to_thread(client.media_info, media_id)
        except Exception as exc:
            raise _classify_instagrapi_exception(exc) from exc

        return {
            "plays": int(getattr(info, "play_count", 0) or getattr(info, "view_count", 0) or 0),
            "likes": int(getattr(info, "like_count", 0) or 0),
            "comments": int(getattr(info, "comment_count", 0) or 0),
            "shares": int(getattr(info, "share_count", 0) or 0),
            "saves": int(getattr(info, "save_count", 0) or 0),
        }

    async def _restore_client(self, session: InstagramSessionToken) -> Any:
        client = self._client_factory()
        try:
            settings = json.loads(session.settings_json)
        except json.JSONDecodeError as exc:
            raise InstagramAuthError(f"settings invalidos: {exc}") from exc
        try:
            await asyncio.to_thread(client.set_settings, settings)
        except Exception as exc:
            raise _classify_instagrapi_exception(exc) from exc
        return client
