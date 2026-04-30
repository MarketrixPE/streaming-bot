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
from streaming_bot.domain.ports.artist_repo import IArtistRepository
from streaming_bot.domain.ports.browser import IBrowserDriver, IBrowserSession
from streaming_bot.domain.ports.browser_rich import IRichBrowserDriver, IRichBrowserSession
from streaming_bot.domain.ports.distributor_monitor import (
    IDistributorMonitor,
    IPanicKillSwitch,
)
from streaming_bot.domain.ports.fingerprint import IFingerprintGenerator
from streaming_bot.domain.ports.history_repo import (
    ISessionRecordRepository,
    IStreamHistoryRepository,
)
from streaming_bot.domain.ports.label_repo import ILabelRepository
from streaming_bot.domain.ports.modem_driver import IModemDriver, IModemPool
from streaming_bot.domain.ports.modem_repo import IModemRepository
from streaming_bot.domain.ports.persona_repo import IPersonaRepository
from streaming_bot.domain.ports.playlist_repo import (
    ICamouflagePool,
    IPlaylistComposer,
    IPlaylistRepository,
    ISeedAccountPool,
)
from streaming_bot.domain.ports.proxy_provider import IProxyProvider
from streaming_bot.domain.ports.session_store import ISessionStore
from streaming_bot.domain.ports.song_repo import ISongRepository
from streaming_bot.domain.ports.spotify_client import ISpotifyClient

__all__ = [
    "IAccountCreator",
    "IAccountRepository",
    "IArtistRepository",
    "IBrowserDriver",
    "IBrowserSession",
    "ICamouflagePool",
    "IDistributorMonitor",
    "IEmailGateway",
    "IFingerprintGenerator",
    "ILabelRepository",
    "IModemDriver",
    "IModemPool",
    "IModemRepository",
    "IPanicKillSwitch",
    "IPersonaFactory",
    "IPersonaRepository",
    "IPlaylistComposer",
    "IPlaylistRepository",
    "IProxyProvider",
    "IRichBrowserDriver",
    "IRichBrowserSession",
    "ISeedAccountPool",
    "ISessionRecordRepository",
    "ISessionStore",
    "ISmsGateway",
    "ISongRepository",
    "ISpotifyClient",
    "IStreamHistoryRepository",
    "WarmingPolicy",
]
