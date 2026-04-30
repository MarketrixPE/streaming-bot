"""EPIC 7 - Monitores defensivos de distribuidores y panic kill-switch.

Este paquete implementa los adaptadores de los puertos:
- ``IDistributorMonitor``: scrapers para DistroKid, OneRPM, aiCom y
  Spotify for Artists, mas un monitor IMAP generico.
- ``IPanicKillSwitch``: kill-switch basado en filesystem que detiene todo el
  ramp-up cuando una alerta critica es detectada.
- ``MonitorOrchestrator``: bucle que corre los monitors en paralelo y dispara
  el kill-switch ante alertas con severity >= CRITICAL.

Reglas de uso:
- Inyectar via ``container.py`` (NO instanciar directo en presentation/).
- Cada monitor reutiliza una sesion de ``IRichBrowserDriver`` con
  ``storage_state`` persistido por plataforma.
- Los keywords de deteccion estan centralizados en ``base_monitor`` para
  que el equipo de seguridad pueda actualizarlos sin tocar la logica.
"""

from streaming_bot.infrastructure.monitors.aicom_monitor import AiComMonitor
from streaming_bot.infrastructure.monitors.base_monitor import (
    KEYWORDS_ACCOUNT_CLOSED,
    KEYWORDS_ACCOUNT_REVIEW,
    KEYWORDS_FILTERED_STREAMS,
    KEYWORDS_PAYMENT_HOLD,
    KEYWORDS_STREAM_MANIPULATION,
    BaseDistributorMonitor,
)
from streaming_bot.infrastructure.monitors.baseline_cache import BaselineCache
from streaming_bot.infrastructure.monitors.distrokid_monitor import DistroKidMonitor
from streaming_bot.infrastructure.monitors.email_imap_monitor import (
    GenericEmailMonitor,
    ImapConfig,
)
from streaming_bot.infrastructure.monitors.monitor_orchestrator import (
    AlertHandler,
    MonitorOrchestrator,
)
from streaming_bot.infrastructure.monitors.onerpm_monitor import OneRPMMonitor
from streaming_bot.infrastructure.monitors.panic_kill_switch import (
    FilesystemPanicKillSwitch,
    KillSwitchCallback,
)
from streaming_bot.infrastructure.monitors.spotify_for_artists_monitor import (
    SpotifyForArtistsMonitor,
)

__all__ = [
    "KEYWORDS_ACCOUNT_CLOSED",
    "KEYWORDS_ACCOUNT_REVIEW",
    "KEYWORDS_FILTERED_STREAMS",
    "KEYWORDS_PAYMENT_HOLD",
    "KEYWORDS_STREAM_MANIPULATION",
    "AiComMonitor",
    "AlertHandler",
    "BaseDistributorMonitor",
    "BaselineCache",
    "DistroKidMonitor",
    "FilesystemPanicKillSwitch",
    "GenericEmailMonitor",
    "ImapConfig",
    "KillSwitchCallback",
    "MonitorOrchestrator",
    "OneRPMMonitor",
    "SpotifyForArtistsMonitor",
]
