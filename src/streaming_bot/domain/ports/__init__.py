"""Puertos: interfaces que el dominio define para que la infra implemente.

Inversion de dependencias: el dominio NO importa nada de infraestructura.
La infra importa estos protocolos y los implementa.
"""

from streaming_bot.domain.ports.account_creator import (
    IAccountCreator,
    IEmailGateway,
    IPersonaFactory,
    ISmsGateway,
    WarmingPolicy,
)
from streaming_bot.domain.ports.account_repo import IAccountRepository
from streaming_bot.domain.ports.ai_music_generator import (
    AIMusicGenerationError,
    IAIMusicGenerator,
)
from streaming_bot.domain.ports.anomaly_predictor import IAnomalyPredictor
from streaming_bot.domain.ports.artist_repo import IArtistRepository
from streaming_bot.domain.ports.audio_mastering import (
    AudioMasteringError,
    IAudioMastering,
    MasteringProfile,
)
from streaming_bot.domain.ports.browser import IBrowserDriver, IBrowserSession
from streaming_bot.domain.ports.browser_rich import IRichBrowserDriver, IRichBrowserSession
from streaming_bot.domain.ports.captcha_solver import CaptchaSolverError, ICaptchaSolver
from streaming_bot.domain.ports.cover_art_generator import (
    CoverArtGenerationError,
    ICoverArtGenerator,
)
from streaming_bot.domain.ports.deezer_client import (
    DeezerApiError,
    DeezerArtist,
    DeezerTrack,
    IDeezerClient,
)
from streaming_bot.domain.ports.distributor_dispatcher import (
    DistributorAPIError,
    DistributorTransientError,
    IArtistAliasRepository,
    IDistributorDispatcher,
    IReleaseRepository,
)
from streaming_bot.domain.ports.distributor_monitor import (
    IDistributorMonitor,
    IPanicKillSwitch,
)
from streaming_bot.domain.ports.experiment_repo import IExperimentRepository
from streaming_bot.domain.ports.fingerprint import IFingerprintGenerator
from streaming_bot.domain.ports.history_repo import (
    ISessionRecordRepository,
    IStreamHistoryRepository,
)
from streaming_bot.domain.ports.instagram_client import (
    IInstagramClient,
    InstagramAccountInfo,
    InstagramAuthError,
    InstagramChallengeRequired,
    InstagramClientError,
    InstagramMediaResult,
    InstagramSessionToken,
)
from streaming_bot.domain.ports.label_repo import ILabelRepository
from streaming_bot.domain.ports.metadata_generator import (
    IMetadataGenerator,
    MetadataGenerationError,
)
from streaming_bot.domain.ports.modem_driver import IModemDriver, IModemPool
from streaming_bot.domain.ports.modem_repo import IModemRepository
from streaming_bot.domain.ports.persona_memory_repo import (
    IPersonaMemoryRepository,
    PersonaMemoryAggregate,
    PersonaMemoryEvent,
    PersonaMemoryEventType,
)
from streaming_bot.domain.ports.persona_repo import IPersonaRepository
from streaming_bot.domain.ports.playlist_repo import (
    ICamouflagePool,
    IPlaylistComposer,
    IPlaylistRepository,
    ISeedAccountPool,
)
from streaming_bot.domain.ports.proxy_provider import IProxyProvider
from streaming_bot.domain.ports.session_store import ISessionStore
from streaming_bot.domain.ports.smart_link_provider import (
    ClickEvent,
    ISmartLinkProvider,
    SmartLinkProviderError,
)
from streaming_bot.domain.ports.song_repo import ISongRepository
from streaming_bot.domain.ports.soundcloud_client import ISoundcloudClient
from streaming_bot.domain.ports.spotify_client import ISpotifyClient
from streaming_bot.domain.ports.track_health_repo import ITrackHealthRepository
from streaming_bot.domain.ports.variant_assignment_repo import IVariantAssignmentRepository

__all__ = [
    "AIMusicGenerationError",
    "AudioMasteringError",
    "CaptchaSolverError",
    "ClickEvent",
    "CoverArtGenerationError",
    "DeezerApiError",
    "DeezerArtist",
    "DeezerTrack",
    "DistributorAPIError",
    "DistributorTransientError",
    "IAIMusicGenerator",
    "IAccountCreator",
    "IAccountRepository",
    "IAnomalyPredictor",
    "IArtistAliasRepository",
    "IArtistRepository",
    "IAudioMastering",
    "IBrowserDriver",
    "IBrowserSession",
    "ICamouflagePool",
    "ICaptchaSolver",
    "ICoverArtGenerator",
    "IDeezerClient",
    "IDistributorDispatcher",
    "IDistributorMonitor",
    "IEmailGateway",
    "IExperimentRepository",
    "IFingerprintGenerator",
    "IInstagramClient",
    "ILabelRepository",
    "IMetadataGenerator",
    "IModemDriver",
    "IModemPool",
    "IModemRepository",
    "IPanicKillSwitch",
    "IPersonaFactory",
    "IPersonaMemoryRepository",
    "IPersonaRepository",
    "IPlaylistComposer",
    "IPlaylistRepository",
    "IProxyProvider",
    "IReleaseRepository",
    "IRichBrowserDriver",
    "IRichBrowserSession",
    "ISeedAccountPool",
    "ISessionRecordRepository",
    "ISessionStore",
    "ISmartLinkProvider",
    "ISmsGateway",
    "ISongRepository",
    "ISoundcloudClient",
    "ISpotifyClient",
    "IStreamHistoryRepository",
    "ITrackHealthRepository",
    "IVariantAssignmentRepository",
    "InstagramAccountInfo",
    "InstagramAuthError",
    "InstagramChallengeRequired",
    "InstagramClientError",
    "InstagramMediaResult",
    "InstagramSessionToken",
    "MasteringProfile",
    "MetadataGenerationError",
    "PersonaMemoryAggregate",
    "PersonaMemoryEvent",
    "PersonaMemoryEventType",
    "SmartLinkProviderError",
    "WarmingPolicy",
]
