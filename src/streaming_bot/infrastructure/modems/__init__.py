"""Driver y pool de modems 4G/5G fisicos (EPIC 3).

Componentes:
- `at_commands`         constantes y parsers AT estandar.
- `quectel_driver`      IModemDriver para Quectel/Huawei via pyserial-asyncio.
- `simulated_driver`    IModemDriver in-memory para tests.
- `interface_binder`    LinuxInterfaceBinder (iptables/ip route, no-op en mac).
- `local_proxy_runner`  DanteProxyRunner (PureSocks5 puro Python por defecto).
- `pure_socks5`         servidor SOCKS5 minimal (RFC 1928).
- `modem_pool`          IModemPool con cooldowns + workers de salud/rotacion.
- `modem_proxy_provider` adapter IProxyProvider sobre el ModemPool.
"""

from streaming_bot.infrastructure.modems.interface_binder import LinuxInterfaceBinder
from streaming_bot.infrastructure.modems.local_proxy_runner import DanteProxyRunner
from streaming_bot.infrastructure.modems.modem_pool import ModemPool
from streaming_bot.infrastructure.modems.modem_proxy_provider import ModemPoolProxyProvider
from streaming_bot.infrastructure.modems.pure_socks5 import PureSocks5Server, Socks5Credentials
from streaming_bot.infrastructure.modems.quectel_driver import HttpViaModem, QuectelModemDriver
from streaming_bot.infrastructure.modems.simulated_driver import SimulatedModemDriver

__all__ = [
    "DanteProxyRunner",
    "HttpViaModem",
    "LinuxInterfaceBinder",
    "ModemPool",
    "ModemPoolProxyProvider",
    "PureSocks5Server",
    "QuectelModemDriver",
    "SimulatedModemDriver",
    "Socks5Credentials",
]
