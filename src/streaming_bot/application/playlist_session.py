"""Caso de uso: ejecutar una sesion de playlist con behaviors humanos.

Reemplaza el flujo legacy "stream-cancion-aislada" por un flujo "playlist-first":
una cuenta se conecta a Spotify Web Player, lanza una playlist, y durante
la reproduccion el `HumanBehaviorEngine` ejecuta micro-interacciones (likes,
follows, scrub, etc.) en orden aleatorio segun la probabilidad de la persona.

Diseño:
- Inyeccion de dependencias completa por puertos del dominio (DIP).
- La engine es construida via factory para tener `session_id` y `persona`
  ya enlazados.
- Reintentos automaticos sobre `TransientError` con backoff exponencial
  (tenacity, max 3 intentos).
- `PermanentError` desactiva la cuenta inmediatamente.
- Persiste `StreamHistory` por cada track y un unico `SessionRecord` al final.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from streaming_bot.application.behavior_engine import HumanBehaviorEngine
from streaming_bot.domain.exceptions import (
    AuthenticationError,
    PermanentError,
    TransientError,
)
from streaming_bot.domain.history import (
    BehaviorEvent,
    BehaviorType,
    SessionRecord,
    StreamHistory,
    StreamOutcome,
)
from streaming_bot.domain.persona import Persona
from streaming_bot.domain.playlist import Playlist, PlaylistTrack

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

    from streaming_bot.domain.entities import Account
    from streaming_bot.domain.ports.account_repo import IAccountRepository
    from streaming_bot.domain.ports.browser_rich import (
        IRichBrowserDriver,
        IRichBrowserSession,
    )
    from streaming_bot.domain.ports.fingerprint import IFingerprintGenerator
    from streaming_bot.domain.ports.history_repo import (
        ISessionRecordRepository,
        IStreamHistoryRepository,
    )
    from streaming_bot.domain.ports.persona_repo import IPersonaRepository
    from streaming_bot.domain.ports.playlist_repo import IPlaylistRepository
    from streaming_bot.domain.ports.proxy_provider import IProxyProvider
    from streaming_bot.domain.ports.session_store import ISessionStore
    from streaming_bot.domain.ports.song_repo import ISongRepository
    from streaming_bot.domain.value_objects import Fingerprint, ProxyEndpoint
    from streaming_bot.presentation.strategies.spotify import SpotifyWebPlayerStrategy


# Listen mínimo Spotify para contar como stream válido (35s para margen sobre 30s).
MIN_LISTEN_SECONDS = 35
# Tope superior para no eternizar canciones de camuflaje.
MAX_LISTEN_SECONDS = 240


# ── DTOs ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class PlaylistSessionRequest:
    """Solicitud al use case."""

    account_id: str
    playlist_id: str
    target_song_uris: frozenset[str]
    min_streams: int = 6
    max_streams: int = 15


@dataclass(slots=True)
class _SessionContext:
    """Contexto interno construido durante `_prepare_context`.

    Mutable solo en `record` y `account` (se mutan al cierre).
    """

    account: Account
    persona: Persona
    playlist: Playlist
    proxy: ProxyEndpoint | None
    fingerprint: Fingerprint
    storage_state: dict[str, Any] | None
    record: SessionRecord
    engine: HumanBehaviorEngine
    log: BoundLogger
    proxy_country: str | None
    proxy_ip_hash: str | None
    wall_clock_start: float


@dataclass(frozen=True, slots=True)
class PlaylistSessionResult:
    """Resultado de la sesion."""

    session_id: str
    completed_streams: int
    target_streams: int
    duration_seconds: int
    outcome: str  # "success" | "partial" | "failed" | "auth_failed"
    behaviors_count: int


# ── Factory type alias ─────────────────────────────────────────────────────
EngineFactory = Callable[[Persona, str], HumanBehaviorEngine]


def _make_engine_factory(
    logger: BoundLogger,
    rng_seed: int | None = None,
) -> EngineFactory:
    """Factory por defecto para crear engines en sesiones reales."""

    def _factory(persona: Persona, session_id: str) -> HumanBehaviorEngine:
        return HumanBehaviorEngine(
            persona=persona,
            session_id=session_id,
            rng_seed=rng_seed,
            logger=logger,
        )

    return _factory


# ── Use case ───────────────────────────────────────────────────────────────
class PlaylistSessionUseCase:
    """Orquesta una sesion de playlist con behaviors humanos."""

    def __init__(
        self,
        *,
        browser: IRichBrowserDriver,
        accounts: IAccountRepository,
        proxies: IProxyProvider,
        fingerprints: IFingerprintGenerator,
        sessions: ISessionStore,
        personas: IPersonaRepository,
        songs: ISongRepository,
        playlists: IPlaylistRepository,
        history: IStreamHistoryRepository,
        session_records: ISessionRecordRepository,
        strategy: SpotifyWebPlayerStrategy,
        engine_factory: EngineFactory | None = None,
        logger: BoundLogger,
        rng_seed: int | None = None,
    ) -> None:
        self._browser = browser
        self._accounts = accounts
        self._proxies = proxies
        self._fingerprints = fingerprints
        self._sessions = sessions
        self._personas = personas
        self._songs = songs
        self._playlists = playlists
        self._history = history
        self._session_records = session_records
        self._strategy = strategy
        self._engine_factory = engine_factory or _make_engine_factory(logger, rng_seed)
        self._log = logger
        # Aleatoriedad para variar scheduling; no es seguridad criptografica.
        self._rng = random.Random(rng_seed) if rng_seed is not None else random.Random()  # noqa: S311

    # ── Entry point ───────────────────────────────────────────────────────
    async def execute(self, request: PlaylistSessionRequest) -> PlaylistSessionResult:
        """Ejecuta la sesion con retry automatico sobre TransientError."""
        log = self._log.bind(
            account_id=request.account_id,
            playlist_id=request.playlist_id,
        )

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1.5, min=1, max=15),
                retry=retry_if_exception_type(TransientError),
                reraise=True,
            ):
                with attempt:
                    return await self._run_session(request, log)
        except AuthenticationError as exc:
            log.exception("session.auth_failed", error=str(exc))
            await self._deactivate_account(request.account_id, reason=str(exc))
            return PlaylistSessionResult(
                session_id="",
                completed_streams=0,
                target_streams=0,
                duration_seconds=0,
                outcome="auth_failed",
                behaviors_count=0,
            )
        except PermanentError as exc:
            log.exception("session.permanent_failed", error=str(exc))
            await self._deactivate_account(request.account_id, reason=str(exc))
            return PlaylistSessionResult(
                session_id="",
                completed_streams=0,
                target_streams=0,
                duration_seconds=0,
                outcome="failed",
                behaviors_count=0,
            )
        except TransientError as exc:
            log.exception("session.transient_exhausted", error=str(exc))
            return PlaylistSessionResult(
                session_id="",
                completed_streams=0,
                target_streams=0,
                duration_seconds=0,
                outcome="failed",
                behaviors_count=0,
            )

        # Defensive: AsyncRetrying garantiza retorno en `with attempt`.
        raise RuntimeError("unreachable: AsyncRetrying no produjo intentos")

    # ── Core flow ─────────────────────────────────────────────────────────
    async def _run_session(
        self,
        request: PlaylistSessionRequest,
        log: BoundLogger,
    ) -> PlaylistSessionResult:
        ctx = await self._prepare_context(request, log)
        log = ctx.log
        log.info("session.start", playlist_tracks=ctx.playlist.total_tracks)

        try:
            counts = await self._run_browser_session(ctx, request)
        except TransientError:
            if ctx.proxy is not None:
                await self._proxies.report_failure(ctx.proxy, reason="transient_error")
            raise
        except (AuthenticationError, PermanentError):
            await self._sessions.delete(ctx.account.id)
            raise

        return await self._finalize_session(ctx, request, counts)

    async def _prepare_context(
        self,
        request: PlaylistSessionRequest,
        log: BoundLogger,
    ) -> _SessionContext:
        """Carga deps, valida y prepara el contexto inmutable de la sesion."""
        started_at = datetime.now(UTC)
        wall_clock_start = time.monotonic()

        account = await self._accounts.get(request.account_id)
        if not account.status.is_usable:
            raise PermanentError(f"account_not_usable:{account.status.state}")

        persona = await self._personas.get(account.id)
        if persona is None:
            raise PermanentError(f"persona_missing_for_account:{account.id}")

        playlist = await self._playlists.get(request.playlist_id)
        if playlist is None:
            raise PermanentError(f"playlist_missing:{request.playlist_id}")
        if not playlist.tracks:
            raise PermanentError(f"playlist_empty:{request.playlist_id}")

        proxy = await self._proxies.acquire(country=persona.country)
        fingerprint = self._fingerprints.coherent_for(proxy, fallback_country=persona.country)
        storage_state = await self._sessions.load(account.id)

        proxy_country = proxy.country.value if proxy and proxy.country else None
        proxy_ip_hash = hashlib.sha256(proxy.host.encode()).hexdigest()[:16] if proxy else None
        record = SessionRecord.new(
            account_id=account.id,
            started_at=started_at,
            proxy_country=proxy_country,
            proxy_ip_hash=proxy_ip_hash,
            user_agent=fingerprint.user_agent,
        )
        engine = self._engine_factory(persona, record.session_id)
        bound_log = log.bind(session_id=record.session_id, proxy=proxy_country or "direct")

        return _SessionContext(
            account=account,
            persona=persona,
            playlist=playlist,
            proxy=proxy,
            fingerprint=fingerprint,
            storage_state=storage_state,
            record=record,
            engine=engine,
            log=bound_log,
            proxy_country=proxy_country,
            proxy_ip_hash=proxy_ip_hash,
            wall_clock_start=wall_clock_start,
        )

    async def _run_browser_session(
        self,
        ctx: _SessionContext,
        request: PlaylistSessionRequest,
    ) -> tuple[int, int, int]:
        """Abre el browser, hace login si aplica, y reproduce la playlist."""
        async with self._browser.session(
            proxy=ctx.proxy,
            fingerprint=ctx.fingerprint,
            storage_state=ctx.storage_state,
        ) as page:
            await self._login_if_needed(page, ctx.account, ctx.log)
            await self._save_session_state(page, ctx.account.id)
            await self._start_playlist(page, ctx.playlist, ctx.log)

            return await self._play_loop(
                page=page,
                playlist=ctx.playlist,
                target_uris=request.target_song_uris,
                engine=ctx.engine,
                record=ctx.record,
                request=request,
                account_id=ctx.account.id,
                proxy_country=ctx.proxy_country,
                proxy_ip_hash=ctx.proxy_ip_hash,
            )

    async def _finalize_session(
        self,
        ctx: _SessionContext,
        request: PlaylistSessionRequest,
        counts: tuple[int, int, int],
    ) -> PlaylistSessionResult:
        """Persiste record + persona memory y devuelve el resultado."""
        completed, target_completed, skipped = counts
        record = ctx.record
        engine = ctx.engine

        record.target_streams_attempted = target_completed
        record.camouflage_streams_attempted = completed - target_completed
        record.streams_counted = completed
        record.skips = skipped
        record.likes_given = len(engine.memory_delta.liked_uris)
        record.saves_given = len(engine.memory_delta.saved_uris)
        record.follows_given = len(engine.memory_delta.followed_artists)
        record.completed_normally = completed >= request.min_streams
        record.ended_at = datetime.now(UTC)

        engine.apply_memory_to_persona(ctx.persona)
        await self._personas.update_memory(ctx.persona)
        await self._session_records.add(record)
        ctx.account.mark_used()
        await self._accounts.update(ctx.account)
        if ctx.proxy is not None:
            await self._proxies.report_success(ctx.proxy)

        duration_seconds = int(time.monotonic() - ctx.wall_clock_start)
        outcome = "success" if completed >= request.min_streams else "partial"
        ctx.log.info(
            "session.complete",
            completed=completed,
            target_completed=target_completed,
            outcome=outcome,
            duration_seconds=duration_seconds,
        )
        return PlaylistSessionResult(
            session_id=record.session_id,
            completed_streams=completed,
            target_streams=target_completed,
            duration_seconds=duration_seconds,
            outcome=outcome,
            behaviors_count=len(record.behavior_events),
        )

    # ── Sub-flujos ────────────────────────────────────────────────────────
    async def _login_if_needed(
        self,
        page: IRichBrowserSession,
        account: Account,
        log: BoundLogger,
    ) -> None:
        if await self._strategy.is_logged_in(page):
            log.info("auth.skipped", reason="cached_session")
            return
        log.info("auth.login.start")
        await self._strategy.login(page, account)
        log.info("auth.login.success")

    async def _save_session_state(
        self,
        page: IRichBrowserSession,
        account_id: str,
    ) -> None:
        try:
            state = await page.storage_state()
        except Exception as exc:
            self._log.warning("session.state_save_failed", error=str(exc))
            return
        await self._sessions.save(account_id, state)

    async def _start_playlist(
        self,
        page: IRichBrowserSession,
        playlist: Playlist,
        log: BoundLogger,
    ) -> None:
        if not playlist.spotify_id:
            raise PermanentError(f"playlist sin spotify_id: {playlist.id}")
        url = f"https://open.spotify.com/playlist/{playlist.spotify_id}"
        try:
            await page.goto(url, wait_until="domcontentloaded")
        except Exception as exc:
            raise TransientError(f"no se pudo abrir playlist {url}: {exc}") from exc

        await self._strategy.wait_for_player_ready(page)
        # Click sobre el play button principal para arrancar.
        try:
            await page.click('[data-testid="play-button"]')
        except Exception as exc:
            log.warning("playlist.play_button_missing", error=str(exc))

    async def _play_loop(
        self,
        *,
        page: IRichBrowserSession,
        playlist: Playlist,
        target_uris: frozenset[str],
        engine: HumanBehaviorEngine,
        record: SessionRecord,
        request: PlaylistSessionRequest,
        account_id: str,
        proxy_country: str | None,
        proxy_ip_hash: str | None,
    ) -> tuple[int, int, int]:
        """Recorre la playlist track por track. Devuelve (completed, target, skipped)."""
        completed = 0
        target_completed = 0
        skipped = 0
        max_streams = max(request.min_streams, request.max_streams)

        for idx, track in enumerate(playlist.tracks):
            if completed >= max_streams:
                break

            track_uri = track.track_uri
            is_target = track_uri in target_uris

            await self._strategy.wait_for_player_ready(page)
            actual_uri = (await self._strategy.get_current_track_uri(page)) or track_uri

            listen_seconds = self._listen_seconds_for_track(track, is_target=is_target)

            history_started = datetime.now(UTC)
            should_skip = self._should_skip(track, is_target=is_target)
            if should_skip:
                # Skip antes de los 30s no cuenta como stream.
                listen_seconds = self._rng.randint(5, 25)

            await self._mark_stream_start(record, actual_uri)
            await self._run_inline_behaviors(page, engine, record, idx)

            await asyncio.sleep(listen_seconds)

            outcome: StreamOutcome
            if should_skip:
                outcome = StreamOutcome.SKIPPED
                skipped += 1
                await page.press_key("MediaTrackNext")
            elif listen_seconds >= MIN_LISTEN_SECONDS:
                outcome = StreamOutcome.COUNTED
                completed += 1
                if is_target:
                    target_completed += 1
                engine.memory_delta.add_stream(
                    minutes=max(listen_seconds // 60, 1),
                    counted=True,
                )
            else:
                outcome = StreamOutcome.PARTIAL

            history = StreamHistory.new(
                account_id=account_id,
                song_uri=actual_uri,
                artist_uri=track.artist_uri or "",
                occurred_at=history_started,
                duration_listened_seconds=listen_seconds,
                outcome=outcome,
                session_id=record.session_id,
            )
            history.proxy_country = proxy_country
            history.proxy_ip_hash = proxy_ip_hash
            await self._history.add(history)

            await self._mark_stream_complete(record, actual_uri, outcome)

            if completed >= request.min_streams and self._rng.random() < 0.20:
                # Pequena chance de cortar la sesion organicamente al cumplir minimo.
                break

        return completed, target_completed, skipped

    async def _run_inline_behaviors(
        self,
        page: IRichBrowserSession,
        engine: HumanBehaviorEngine,
        record: SessionRecord,
        track_index: int,
    ) -> None:
        """Ejecuta una bateria de behaviors en orden aleatorio para este track.

        Cada behavior decide internamente si actua segun la probabilidad de
        la persona. Solo agregamos al record los eventos no-None.
        """
        candidates = [
            engine.maybe_like_current_track,
            engine.maybe_save_to_library,
            engine.maybe_add_to_playlist,
            engine.maybe_add_to_queue,
            engine.maybe_open_canvas,
            engine.maybe_open_lyrics,
            engine.maybe_click_credits,
            engine.maybe_open_share_modal,
            engine.maybe_follow_artist,
            engine.maybe_view_artist_about,
            engine.maybe_play_other_song_of_artist,
            engine.maybe_view_discography,
            engine.maybe_volume_change,
            engine.maybe_mute_toggle,
            engine.maybe_repeat_toggle,
            engine.maybe_shuffle_toggle,
            engine.maybe_pause_resume,
            engine.maybe_scrub_forward,
            engine.maybe_scrub_backward,
            engine.maybe_toggle_time_remaining,
            engine.maybe_open_devices_modal,
            engine.maybe_visit_home,
            engine.maybe_visit_search,
            engine.maybe_visit_library,
            engine.maybe_scroll_sidebar,
            engine.maybe_toggle_view_mode,
            engine.maybe_open_notifications,
            engine.maybe_open_settings,
            engine.maybe_long_pause_distracted,
            engine.maybe_tab_blur_event,
        ]
        # Solo en el primer track ofrecemos behaviors macro de "discover/made for you".
        if track_index == 0:
            candidates.extend(
                [
                    engine.maybe_listen_discover_weekly,
                    engine.maybe_listen_made_for_you,
                ]
            )
        self._rng.shuffle(candidates)

        for behavior in candidates:
            try:
                event = await behavior(page)
            except TransientError:
                raise
            except Exception as exc:
                self._log.warning(
                    "behavior.failed",
                    behavior=behavior.__name__,
                    error=str(exc),
                )
                continue
            if event is not None:
                record.add_event(event)

    # ── Utilidades ────────────────────────────────────────────────────────
    def _listen_seconds_for_track(
        self,
        track: PlaylistTrack,
        *,
        is_target: bool,
    ) -> int:
        """Calcula tiempo de escucha humano. Mín 35s para targets."""
        duration_s = track.duration_ms // 1000 if track.duration_ms else 0
        duration_s = max(duration_s, MIN_LISTEN_SECONDS)

        if is_target:
            # Targets se escuchan al menos al umbral, idealmente 70-95% del track.
            low = MIN_LISTEN_SECONDS
            high = max(int(duration_s * 0.95), MIN_LISTEN_SECONDS + 5)
            return self._rng.randint(low, min(high, MAX_LISTEN_SECONDS))

        # Camuflaje: 50-100% del track.
        low = max(int(duration_s * 0.50), MIN_LISTEN_SECONDS)
        high = max(int(duration_s * 1.00), low + 1)
        return self._rng.randint(low, min(high, MAX_LISTEN_SECONDS))

    def _should_skip(
        self,
        track: PlaylistTrack,
        *,
        is_target: bool,
    ) -> bool:
        """Decide si se hace skip prematuro del track. Targets nunca se saltan."""
        if is_target:
            return False
        # Tracks demasiado cortas tienen mayor skip-rate (mas humano).
        base_skip = 0.10
        if track.duration_ms and track.duration_ms < 60_000:
            base_skip = 0.20
        return self._rng.random() < base_skip

    async def _mark_stream_start(
        self,
        record: SessionRecord,
        track_uri: str,
    ) -> None:
        record.add_event(
            BehaviorEvent.new(
                session_id=record.session_id,
                type=BehaviorType.STREAM_START,
                occurred_at=datetime.now(UTC),
                target_uri=track_uri,
            )
        )

    async def _mark_stream_complete(
        self,
        record: SessionRecord,
        track_uri: str,
        outcome: StreamOutcome,
    ) -> None:
        kind = (
            BehaviorType.STREAM_COMPLETE
            if outcome == StreamOutcome.COUNTED
            else BehaviorType.STREAM_SKIPPED
        )
        record.add_event(
            BehaviorEvent.new(
                session_id=record.session_id,
                type=kind,
                occurred_at=datetime.now(UTC),
                target_uri=track_uri,
                metadata={"outcome": outcome.value},
            )
        )

    async def _deactivate_account(self, account_id: str, *, reason: str) -> None:
        try:
            account = await self._accounts.get(account_id)
        except Exception as exc:
            self._log.warning("account.lookup_failed", error=str(exc))
            return
        account.deactivate(reason=reason)
        await self._accounts.update(account)
