"""Composition root: cablea todas las dependencias.

Esta es la UNICA capa donde se permite conocer todas las implementaciones
concretas. Aqui materializamos los puertos y los pasamos a los casos de uso.

Estructura:
- `Container.build_legacy(settings)`: stack original (Playwright + repos JSON
  encriptados + sin DB). Sirve para el flujo demo TodoMVC.
- `Container.build(settings)`: stack completo Sprint 2 (Postgres + Camoufox +
  Modems + Monitors + Scheduler + ImportCatalog). Es el stack productivo.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from streaming_bot.application.import_catalog import (
    ImportCatalogService,
    TierClassifier,
)
from streaming_bot.application.orchestrator import OrchestratorConfig, StreamOrchestrator
from streaming_bot.application.stream_song import ISiteStrategy, StreamSongUseCase
from streaming_bot.config import ProxyMode, Settings
from streaming_bot.domain.ports import (
    IAccountRepository,
    IArtistRepository,
    IBrowserDriver,
    IFingerprintGenerator,
    ILabelRepository,
    IPanicKillSwitch,
    IProxyProvider,
    ISessionStore,
    ISongRepository,
)
from streaming_bot.infrastructure.browser import PlaywrightDriver
from streaming_bot.infrastructure.fingerprints import CoherentFingerprintGenerator
from streaming_bot.infrastructure.monitors.panic_kill_switch import (
    FilesystemPanicKillSwitch,
)
from streaming_bot.infrastructure.observability import (
    Metrics,
    configure_logging,
    get_logger,
)
from streaming_bot.infrastructure.persistence.postgres.database import (
    make_engine,
    make_session_factory,
    transactional_session,
)
from streaming_bot.infrastructure.persistence.postgres.repos import (
    PostgresAccountRepository,
    PostgresArtistRepository,
    PostgresLabelRepository,
    PostgresSongRepository,
)
from streaming_bot.infrastructure.proxies import NoProxyProvider, StaticFileProxyProvider
from streaming_bot.infrastructure.repos import EncryptedAccountRepository, FileSessionStore


@dataclass(slots=True)
class LegacyContainer:
    """Container del stack legacy (sin DB). Util para demo TodoMVC."""

    settings: Settings
    browser: IBrowserDriver
    accounts: IAccountRepository
    sessions: ISessionStore
    proxies: IProxyProvider
    fingerprints: IFingerprintGenerator
    metrics: Metrics

    @classmethod
    def build(cls, settings: Settings) -> LegacyContainer:
        configure_logging(
            level=settings.observability.log_level,
            fmt=settings.observability.log_format,
        )
        return cls(
            settings=settings,
            browser=PlaywrightDriver(
                headless=settings.browser.headless,
                slow_mo_ms=settings.browser.slow_mo_ms,
                default_timeout_ms=settings.browser.default_timeout_ms,
            ),
            accounts=EncryptedAccountRepository(
                path=settings.storage.accounts_path,
                master_key=settings.storage.master_key,
            ),
            sessions=FileSessionStore(
                base_dir=settings.storage.sessions_dir,
                master_key=settings.storage.master_key,
            ),
            proxies=_build_proxy_provider(settings),
            fingerprints=CoherentFingerprintGenerator(
                viewport_width=settings.browser.viewport_width,
                viewport_height=settings.browser.viewport_height,
            ),
            metrics=Metrics(),
        )

    def make_orchestrator(self, strategy: ISiteStrategy) -> StreamOrchestrator:
        log = get_logger("streaming_bot.orchestrator")
        use_case = StreamSongUseCase(
            browser=self.browser,
            accounts=self.accounts,
            proxies=self.proxies,
            fingerprints=self.fingerprints,
            sessions=self.sessions,
            strategy=strategy,
            logger=get_logger("streaming_bot.use_case"),
        )
        return StreamOrchestrator(
            use_case=use_case,
            config=OrchestratorConfig(
                concurrency=self.settings.concurrency,
                max_retries=self.settings.max_retries,
                retry_backoff_seconds=self.settings.retry_backoff_seconds,
            ),
            logger=log,
        )


# Mantenemos `Container` como alias para compatibilidad con codigo existente
# que importa `from streaming_bot.container import Container`.
Container = LegacyContainer


@dataclass(slots=True)
class ProductionContainer:
    """Container del stack Sprint 2 (Postgres + Camoufox + Modems + Monitors).

    No instancia browser ni modem pool en `build`: ambos requieren estado
    asincrono y se levantan via `async with container.browser_session()`
    y `async with container.modem_pool()` respectivamente.
    """

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    fingerprints: IFingerprintGenerator
    proxies: IProxyProvider
    panic_kill_switch: IPanicKillSwitch
    metrics: Metrics

    @classmethod
    def build(cls, settings: Settings) -> ProductionContainer:
        configure_logging(
            level=settings.observability.log_level,
            fmt=settings.observability.log_format,
        )
        engine = make_engine(
            settings.database.url,
            echo=settings.database.echo,
        )
        session_factory = make_session_factory(engine)

        kill_switch = FilesystemPanicKillSwitch(
            marker_path=settings.dashboard.panic_kill_switch_path,
            audit_log_path=Path("./data/panic_audit.log"),
            logger=cast(Any, structlog.get_logger("panic_kill_switch")),
        )

        return cls(
            settings=settings,
            engine=engine,
            session_factory=session_factory,
            fingerprints=CoherentFingerprintGenerator(
                viewport_width=settings.browser.viewport_width,
                viewport_height=settings.browser.viewport_height,
            ),
            proxies=_build_proxy_provider(settings),
            panic_kill_switch=kill_switch,
            metrics=Metrics(),
        )

    def session_scope(self) -> AbstractAsyncContextManager[AsyncSession]:
        """Context manager async para una transaccion atomica."""
        return transactional_session(self.session_factory)

    def make_account_repository(self, session: AsyncSession) -> IAccountRepository:
        return PostgresAccountRepository(session)

    def make_artist_repository(self, session: AsyncSession) -> IArtistRepository:
        return PostgresArtistRepository(session)

    def make_label_repository(self, session: AsyncSession) -> ILabelRepository:
        return PostgresLabelRepository(session)

    def make_song_repository(self, session: AsyncSession) -> ISongRepository:
        return PostgresSongRepository(session)

    def make_import_service(
        self,
        *,
        artists: IArtistRepository,
        labels: ILabelRepository,
        songs: ISongRepository,
    ) -> ImportCatalogService:
        return ImportCatalogService(
            artists=artists,
            labels=labels,
            songs=songs,
            classifier=TierClassifier(),
            logger=cast(Any, structlog.get_logger("import_catalog")),
        )

    def make_spotify_client(self) -> Any:
        """Construye SpotifyWebApiClient (client_credentials o user mode)."""
        from streaming_bot.infrastructure.spotify import (  # noqa: PLC0415
            SpotifyConfig,
            SpotifyWebApiClient,
        )

        if not self.settings.spotify.client_id:
            msg = (
                "spotify_credentials_missing: configura SB_SPOTIFY__CLIENT_ID "
                "y SB_SPOTIFY__CLIENT_SECRET en .env"
            )
            raise RuntimeError(msg)

        config = SpotifyConfig(
            client_id=self.settings.spotify.client_id,
            client_secret=self.settings.spotify.client_secret,
            redirect_uri=self.settings.spotify.redirect_uri,
            user_refresh_token=self.settings.spotify.user_refresh_token,
        )
        return SpotifyWebApiClient(config)

    def make_camouflage_pool(self, *, spotify_client: Any) -> Any:
        """Construye PostgresCamouflagePool con el cliente Spotify."""
        from streaming_bot.infrastructure.camouflage import (  # noqa: PLC0415
            PostgresCamouflagePool,
        )

        return PostgresCamouflagePool(  # type: ignore[call-arg]
            session_factory=self.session_factory,
            spotify_client=spotify_client,
        )

    def make_playlist_composer(self, *, camouflage_pool: Any) -> Any:
        """Construye DefaultPlaylistComposer con pool de camuflaje."""
        from streaming_bot.application.playlists import (  # noqa: PLC0415
            ComposerConfig,
            DefaultPlaylistComposer,
        )

        config = ComposerConfig(  # type: ignore[call-arg]
            default_target_ratio=0.30,
            min_playlist_size=10,
            max_playlist_size=100,
        )
        return DefaultPlaylistComposer(  # type: ignore[call-arg]
            camouflage_pool=camouflage_pool,
            config=config,
        )

    def make_camouflage_ingest_service(
        self,
        *,
        spotify_client: Any,
        camouflage_pool: Any,
    ) -> Any:
        """Construye CamouflageIngestService."""
        from streaming_bot.application.camouflage import (  # noqa: PLC0415
            CamouflageIngestService,
        )

        return CamouflageIngestService(  # type: ignore[call-arg]
            spotify_client=spotify_client,
            camouflage_pool=camouflage_pool,
        )

    def make_account_creator(self) -> Any:
        """Construye SpotifyAccountCreator con gateways correspondientes."""
        from streaming_bot.infrastructure.accounts import (  # noqa: PLC0415
            AccountsConfig,
            BrowserforgePersonaFactory,
            MailTmEmailGateway,
            SpotifyAccountCreator,
            StubSmsGateway,
            TwilioSmsGateway,
        )

        use_stub = (
            self.settings.accounts.use_stub_sms or not self.settings.accounts.twilio_account_sid
        )
        sms_gateway = (
            StubSmsGateway()
            if use_stub
            else TwilioSmsGateway(  # type: ignore[call-arg]
                account_sid=self.settings.accounts.twilio_account_sid,
                auth_token=self.settings.accounts.twilio_auth_token,
            )
        )

        email_gateway = MailTmEmailGateway(  # type: ignore[call-arg]
            base_url=self.settings.accounts.mail_tm_base_url,
        )
        persona_factory = BrowserforgePersonaFactory()

        config = AccountsConfig(
            registration_url="https://www.spotify.com/signup",
            verification_timeout_seconds=120,
        )
        return SpotifyAccountCreator(  # type: ignore[call-arg]
            email_gateway=email_gateway,
            sms_gateway=sms_gateway,
            persona_factory=persona_factory,
            config=config,
        )

    async def dispose(self) -> None:
        """Libera recursos asincronos (engine de SQLAlchemy)."""
        await self.engine.dispose()


def _build_proxy_provider(settings: Settings) -> IProxyProvider:
    if settings.proxy.mode == ProxyMode.STATIC_FILE:
        return StaticFileProxyProvider(
            path=settings.proxy.file_path,
            healthcheck_url=settings.proxy.healthcheck_url,
        )
    return NoProxyProvider()
