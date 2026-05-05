"""Puerto ``IInstagramClient``: contrato para clientes de Instagram.

Implementaciones esperadas:
- ``InstagrapiAdapter`` (mobile API privada via instagrapi v2.4.4) para el
  80% del trafico (post Reel, like, follow, comment, info).
- ``PatchrightInstagramFallback`` (browser-based) para el 20% restante:
  login con challenge_required, recovery, casos donde la mobile API esta
  rate-limiteada.

Convenciones:
- Todos los metodos son async y NO bloquean.
- El adapter se encarga de re-hidratar device fingerprint persistido.
- Errores tipados arriba (InstagramAuthError / InstagramTransientError) para
  que la capa de aplicacion decida retry vs fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from streaming_bot.domain.exceptions import PermanentError, TransientError


class InstagramClientError(TransientError):
    """Error generico del cliente IG (rate limit, timeout, 5xx)."""


class InstagramAuthError(PermanentError):
    """Login fallo de forma permanente (password rotada, cuenta baneada)."""


class InstagramChallengeRequired(InstagramClientError):
    """instagrapi devolvio ``challenge_required``: delegar a Patchright fallback."""


@dataclass(frozen=True, slots=True)
class InstagramSessionToken:
    """Token de sesion serializable. Devuelto por ``login`` y reutilizable.

    El adapter persiste y rehidrata desde su propio storage (filesystem,
    redis, postgres). El value object es opaco para la capa de aplicacion.
    """

    username: str
    settings_json: str  # serializacion de Client.get_settings()


@dataclass(frozen=True, slots=True)
class InstagramAccountInfo:
    """Snapshot read-only de una cuenta IG para validacion post-login."""

    username: str
    user_id: int
    follower_count: int
    following_count: int
    media_count: int
    is_private: bool
    is_verified: bool


@dataclass(frozen=True, slots=True)
class InstagramMediaResult:
    """Resultado de un post (Reel, story, foto). Incluye el ``media_id`` IG."""

    media_id: str  # pk numerico devuelto por la API
    code: str  # shortcode (lo que aparece en /p/<code>)
    caption: str


@runtime_checkable
class IInstagramClient(Protocol):
    """Contrato unificado para mobile API + browser fallback.

    No mezcla tipos de instagrapi en la firma para que el dominio quede
    agnostico (DIP). Las funciones devuelven dataclasses propias.
    """

    async def login(
        self,
        *,
        username: str,
        password: str,
        device_fingerprint: dict[str, str],
        previous_session: InstagramSessionToken | None = None,
    ) -> InstagramSessionToken:
        """Inicia sesion. Si ``previous_session`` esta presente la rehidrata
        para evitar nuevo challenge.

        Lanza ``InstagramChallengeRequired`` si IG pide verificacion.
        Lanza ``InstagramAuthError`` si las credenciales son invalidas.
        """
        ...

    async def post_reel(
        self,
        *,
        session: InstagramSessionToken,
        video_path: Path,
        caption: str,
    ) -> InstagramMediaResult:
        """Publica un Reel desde un .mp4 vertical 9:16."""
        ...

    async def post_story(
        self,
        *,
        session: InstagramSessionToken,
        media_path: Path,
        link_url: str | None = None,
    ) -> InstagramMediaResult:
        """Publica una story (foto o video) con sticker de link opcional."""
        ...

    async def follow(
        self,
        *,
        session: InstagramSessionToken,
        target_user_id: int,
    ) -> None: ...

    async def like(
        self,
        *,
        session: InstagramSessionToken,
        media_id: str,
    ) -> None: ...

    async def comment(
        self,
        *,
        session: InstagramSessionToken,
        media_id: str,
        text: str,
    ) -> None: ...

    async def get_account_info(
        self,
        *,
        session: InstagramSessionToken,
    ) -> InstagramAccountInfo: ...

    async def get_media_metrics(
        self,
        *,
        session: InstagramSessionToken,
        media_id: str,
    ) -> dict[str, int]:
        """Devuelve dict crudo con keys ``plays``, ``shares``, ``saves``,
        ``likes``, ``comments``. El caller mapea a ``ReelMetrics``.
        """
        ...
