"""``CrossPlatformSpilloverOrchestrator``: orquesta el ciclo de spillover.

Ciclo end-to-end por track:
1. Resolver cuenta IG sticky para el ``artist_uri`` (provisioning service).
2. Asegurar smart-link (Linkfire o self-hosted) con geo-routing.
3. Generar Reel via ``ReelsGeneratorService``.
4. Postear Reel via ``IInstagramClient.post_reel``.
5. Postear story con sticker de link a la bio.
6. Tirar primera lectura de metricas (best-effort).

NOTA: la correlacion con uplift Spotify se hace OFFLINE en otro servicio
(scheduler / batch monitor). Aqui solo emitimos los eventos que el
orchestrator ML downstream consume (mediante el repo de Reels).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

from streaming_bot.domain.meta.instagram_account import InstagramAccount
from streaming_bot.domain.meta.reel import Reel, ReelMetrics
from streaming_bot.domain.ports.instagram_client import (
    IInstagramClient,
    InstagramChallengeRequired,
    InstagramSessionToken,
)
from streaming_bot.domain.ports.smart_link_provider import ISmartLinkProvider

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

    from streaming_bot.application.meta.account_provisioning import (
        InstagramAccountProvisioningService,
    )
    from streaming_bot.application.meta.reels_generator import ReelsGeneratorService
    from streaming_bot.domain.artist import Artist
    from streaming_bot.domain.meta.smart_link import SmartLink
    from streaming_bot.domain.value_objects import Country


@runtime_checkable
class IReelRepository(Protocol):
    """Persistencia de ``Reel`` para correlacion downstream."""

    async def add(self, reel: Reel) -> None: ...

    async def update(self, reel: Reel) -> None: ...

    async def list_by_account(self, account_id: str) -> list[Reel]: ...


@dataclass(frozen=True, slots=True)
class SpilloverCycleResult:
    """Resultado de un ciclo. Si ``posted`` es False, ``failure_reason`` esta
    poblado y la cuenta puede haber pasado a CHALLENGE.
    """

    artist_id: str
    track_uri: str
    account_id: str
    reel_id: str | None
    posted: bool
    failure_reason: str | None = None


# Resolutor de credenciales: dado el username, devuelve (password, prev_session).
# El caller inyecta esto desde su secret store (vault, KMS).
CredentialsResolver = Callable[[str], "Awaitable[tuple[str, InstagramSessionToken | None]]"]


class CrossPlatformSpilloverOrchestrator:
    """Conecta provisioning, smart link, reels generator e instagrapi en un
    flujo unico que se llama por (artist, track).
    """

    def __init__(
        self,
        *,
        provisioning: InstagramAccountProvisioningService,
        reels_generator: ReelsGeneratorService,
        smart_link_provider: ISmartLinkProvider,
        instagram_client: IInstagramClient,
        reels: IReelRepository,
        credentials_resolver: CredentialsResolver,
        smart_link_base_url: str,
        logger: BoundLogger | None = None,
    ) -> None:
        self._provisioning = provisioning
        self._reels_gen = reels_generator
        self._smart_links = smart_link_provider
        self._ig = instagram_client
        self._reels_repo = reels
        self._creds = credentials_resolver
        self._smart_link_base_url = smart_link_base_url
        self._log: BoundLogger = logger or structlog.get_logger("meta.spillover")

    async def run_cycle(
        self,
        *,
        artist: Artist,
        track_uri: str,
        track_title: str,
        artist_name: str,
        audio_track_path: Path,
        niche: str,
        target_dsps: dict[Country, dict[str, str]],
        primary_country: Country,
        mood: str | None = None,
    ) -> SpilloverCycleResult:
        """Ejecuta un ciclo completo. No re-lanza excepciones del cliente IG:
        las captura y devuelve ``SpilloverCycleResult(posted=False, ...)`` para
        que el caller (scheduler) decida retry vs marcar artista en cooldown.
        """
        log = self._log.bind(artist_id=artist.id, track_uri=track_uri, niche=niche)
        log.info("spillover.cycle.start")

        provisioning_result = await self._provisioning.provision_for_artist(artist)
        account = provisioning_result.account
        if not account.is_postable:
            log.warning(
                "spillover.account_not_postable",
                username=account.username,
                status=account.status.value,
            )
            return SpilloverCycleResult(
                artist_id=artist.id,
                track_uri=track_uri,
                account_id=account.id,
                reel_id=None,
                posted=False,
                failure_reason=f"account_status={account.status.value}",
            )

        smart_link = await self._ensure_smart_link(track_uri=track_uri, target_dsps=target_dsps)
        log.debug("spillover.smart_link_ready", short_id=smart_link.short_id)

        bundle = await self._reels_gen.generate(
            account_id=account.id,
            track_uri=track_uri,
            track_title=track_title,
            artist_name=artist_name,
            artist_uri=account.artist_uri,
            audio_track_path=audio_track_path,
            niche=niche,
            smart_link=smart_link,
            smart_link_base_url=self._smart_link_base_url,
            smart_link_country=primary_country,
            mood=mood,
        )

        reel = bundle.reel
        await self._reels_repo.add(reel)

        try:
            session = await self._open_session(account)
        except InstagramChallengeRequired as exc:
            account.mark_challenge(str(exc))
            return SpilloverCycleResult(
                artist_id=artist.id,
                track_uri=track_uri,
                account_id=account.id,
                reel_id=reel.id,
                posted=False,
                failure_reason=f"challenge_required: {exc}",
            )

        try:
            media = await self._ig.post_reel(
                session=session,
                video_path=reel.video_path,
                caption=reel.full_caption(),
            )
        except InstagramChallengeRequired as exc:
            account.mark_challenge(str(exc))
            return SpilloverCycleResult(
                artist_id=artist.id,
                track_uri=track_uri,
                account_id=account.id,
                reel_id=reel.id,
                posted=False,
                failure_reason=f"challenge_required: {exc}",
            )
        except Exception as exc:
            log.error("spillover.post_reel_failed", error=str(exc))
            return SpilloverCycleResult(
                artist_id=artist.id,
                track_uri=track_uri,
                account_id=account.id,
                reel_id=reel.id,
                posted=False,
                failure_reason=f"post_failed: {exc}",
            )

        reel.mark_posted(media_id=media.media_id, posted_at=datetime.now(UTC))
        await self._reels_repo.update(reel)
        log.info("spillover.cycle.posted", media_id=media.media_id, code=media.code)

        await self._post_story_with_link(
            session=session,
            video_path=reel.video_path,
            link_url=reel.smart_link,
            log=log,
        )

        await self._poll_initial_metrics(reel=reel, session=session, log=log)

        return SpilloverCycleResult(
            artist_id=artist.id,
            track_uri=track_uri,
            account_id=account.id,
            reel_id=reel.id,
            posted=True,
        )

    async def _ensure_smart_link(
        self,
        *,
        track_uri: str,
        target_dsps: dict[Country, dict[str, str]],
    ) -> SmartLink:
        """Crea el smart-link si no existe (idempotente al nivel adapter)."""
        return await self._smart_links.create_link(
            track_uri=track_uri,
            target_dsps=target_dsps,
        )

    async def _open_session(self, account: InstagramAccount) -> InstagramSessionToken:
        password, previous = await self._creds(account.username)
        token = await self._ig.login(
            username=account.username,
            password=password,
            device_fingerprint=account.device_fingerprint,
            previous_session=previous,
        )
        account.record_login()
        return token

    async def _post_story_with_link(
        self,
        *,
        session: InstagramSessionToken,
        video_path: Path,
        link_url: str,
        log: BoundLogger,
    ) -> None:
        """Best-effort: si la story falla, el ciclo igual cuenta como exitoso
        (Reel posteado). No queremos que un fallo de story cancele el reel.
        """
        try:
            await self._ig.post_story(
                session=session,
                media_path=video_path,
                link_url=link_url,
            )
            log.debug("spillover.story_posted")
        except Exception as exc:
            log.warning("spillover.story_failed", error=str(exc))

    async def _poll_initial_metrics(
        self,
        *,
        reel: Reel,
        session: InstagramSessionToken,
        log: BoundLogger,
    ) -> None:
        if reel.media_id is None:
            return
        try:
            raw = await self._ig.get_media_metrics(session=session, media_id=reel.media_id)
        except Exception as exc:
            log.warning("spillover.metrics_initial_failed", error=str(exc))
            return
        reel.update_metrics(
            ReelMetrics(
                plays=int(raw.get("plays", 0)),
                shares=int(raw.get("shares", 0)),
                saves=int(raw.get("saves", 0)),
                likes=int(raw.get("likes", 0)),
                comments=int(raw.get("comments", 0)),
            ),
        )
        await self._reels_repo.update(reel)
