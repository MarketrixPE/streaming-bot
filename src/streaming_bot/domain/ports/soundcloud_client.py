"""Puerto `ISoundcloudClient`: contrato READ contra la API privada v2.

Diseno DIP: el dominio define el contrato; la infraestructura
(`infrastructure/soundcloud/soundcloud_v2_client.py`) lo implementa via
`api-v2.soundcloud.com` con scraping de `client_id` desde la homepage.

Solo expone metodos READ baratos (metadata, search, user lookup, plays
count). Las acciones write (login, like, repost, follow, comment) viven en
la strategy Patchright porque requieren resolver retos DataDome y mantener
sesion humana.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from streaming_bot.domain.soundcloud.models import SoundcloudTrack, SoundcloudUser


@runtime_checkable
class ISoundcloudClient(Protocol):
    """Cliente READ de la API privada v2 de SoundCloud."""

    async def get_track(self, track_id_or_urn: str | int) -> SoundcloudTrack | None:
        """Devuelve metadata de un track. None si 404."""
        ...

    async def get_user(self, user_id_or_permalink: str | int) -> SoundcloudUser | None:
        """Devuelve metadata de un usuario/artista. None si 404."""
        ...

    async def search_tracks(
        self,
        *,
        query: str,
        limit: int = 20,
    ) -> list[SoundcloudTrack]:
        """Busca tracks por texto libre (titulo, artista, tag)."""
        ...

    async def get_track_plays_count(self, track_id_or_urn: str | int) -> int:
        """Devuelve playback_count actual del track. 0 si no existe.

        Wrapper conveniente sobre `get_track` para alimentar al
        `PremierEligibilityService` sin forzarlo a desempaquetar el DTO.
        """
        ...
