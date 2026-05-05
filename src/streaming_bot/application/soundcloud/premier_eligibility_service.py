"""Servicio de elegibilidad Premier para tracks SoundCloud.

Combina dos puertos: `ISoundcloudClient` (lookup de track + owner para
extraer follower count y playback total) y un proveedor de plays
monetizables 30d. La distincion importa: el playback_count global incluye
plays NO monetizables (paises fuera del royalty pool); el caller debe
medir aparte cuantos vienen de territorios monetizables.

Para Q1 2026 trabajamos contra una abstraccion sencilla: una funcion
async `monetizable_plays_provider(track_urn) -> int`. La implementacion
real puede consultar Datadog, ClickHouse o el mismo SoundCloud Insights
API; el caso de uso no necesita saber de donde vienen los numeros.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from streaming_bot.domain.soundcloud.models import (
    DEFAULT_PREMIER_FOLLOWER_THRESHOLD,
    DEFAULT_PREMIER_PLAYS_THRESHOLD,
    PremierEligibility,
)

if TYPE_CHECKING:
    from streaming_bot.domain.ports.soundcloud_client import ISoundcloudClient


class IMonetizablePlaysProvider(Protocol):
    """Cuantos plays monetizables tiene un track en los ultimos 30 dias.

    Lo dejamos como protocol para no atar el caso de uso a una metric DB
    concreta (Datadog, ClickHouse, SoundCloud Insights, etc).
    """

    async def __call__(self, track_urn: str) -> int: ...


class PremierEligibilityService:
    """Calcula `PremierEligibility` y devuelve el gap a monetizacion.

    Dependencias inyectadas (DIP):
    - `client`: lookup de track + user en la API privada v2.
    - `monetizable_plays_provider`: callable async con plays 30d.

    El servicio nunca lanza por el lado de negocio: si el track o el user
    no existen devuelve `None` para que el caller decida (skip vs error).
    """

    def __init__(
        self,
        *,
        client: ISoundcloudClient,
        monetizable_plays_provider: IMonetizablePlaysProvider,
        threshold_followers: int = DEFAULT_PREMIER_FOLLOWER_THRESHOLD,
        threshold_plays: int = DEFAULT_PREMIER_PLAYS_THRESHOLD,
    ) -> None:
        self._client = client
        self._monetizable_plays_provider = monetizable_plays_provider
        self._threshold_followers = threshold_followers
        self._threshold_plays = threshold_plays

    async def evaluate(self, track_id_or_urn: str | int) -> PremierEligibility | None:
        """Devuelve elegibilidad para un track. None si no existe."""
        track = await self._client.get_track(track_id_or_urn)
        if track is None:
            return None
        owner = await self._client.get_user(track.user_id)
        if owner is None:
            return None
        monetizable_plays = await self._monetizable_plays_provider(track.urn)
        return PremierEligibility(
            track_urn=track.urn,
            followers=owner.followers_count,
            monetizable_plays_30d=monetizable_plays,
            threshold_followers=self._threshold_followers,
            threshold_plays=self._threshold_plays,
        )
