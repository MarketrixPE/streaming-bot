"""Puertos para el pool de modems 4G/5G fisicos.

Dos niveles de abstraccion:
- `IModemDriver`: control de UN modem fisico (AT commands, rotacion IP, health).
- `IModemPool`: gestion del pool completo (reparto, cooldowns, salud agregada).

La implementacion fisica vivira en `infrastructure/modems/` y usara pyserial
para AT commands + iptables/ip route para tunelar trafico via interfaz movil.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from streaming_bot.domain.modem import Modem
from streaming_bot.domain.value_objects import Country, ProxyEndpoint

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@runtime_checkable
class IModemDriver(Protocol):
    """Driver de bajo nivel para UN modem fisico.

    Implementaciones esperadas:
    - QuectelDriver (AT commands para Quectel EG25-G / RM500Q).
    - HuaweiDriver (Huawei E3372, hilink).
    - SimulatedModemDriver (fixture para tests).
    """

    async def health_check(self, modem: Modem) -> bool:
        """Verifica que el modem responde y tiene IP publica."""
        ...

    async def rotate_ip(self, modem: Modem) -> str | None:
        """Fuerza reconexion para obtener nueva IP publica.

        Devuelve la nueva IP publica o None si fallo. La operacion
        marca el modem como ROTATING durante el proceso.
        """
        ...

    async def get_public_ip(self, modem: Modem) -> str | None:
        """Consulta la IP publica actual via canal del modem (no via OS)."""
        ...

    async def get_signal_strength(self, modem: Modem) -> int:
        """Devuelve RSSI/RSRP en dBm. Util para health checks."""
        ...

    async def reset(self, modem: Modem) -> None:
        """Reinicia el modem (AT+CFUN=1,1)."""
        ...

    async def send_at_command(self, modem: Modem, command: str) -> str:
        """Escape hatch: envia AT command crudo y devuelve respuesta."""
        ...


@runtime_checkable
class IModemPool(Protocol):
    """Pool de modems con asignacion, balanceo y cooldowns.

    Reparte modems entre cuentas activas garantizando:
    - Coherencia geo: cuenta-PE recibe modem-PE.
    - Rate limit: max 3 cuentas distintas por modem por dia.
    - Cooldown: 5 min entre asignaciones del mismo modem.
    - Salud: solo modems READY se asignan.
    """

    async def acquire(
        self,
        *,
        country: Country,
        timeout_seconds: float = 30.0,
    ) -> Modem | None:
        """Adquiere un modem del pais solicitado. Bloquea el modem para uso exclusivo."""
        ...

    async def release(
        self,
        modem: Modem,
        *,
        streams_served: int = 0,
        rotate_ip: bool = True,
    ) -> None:
        """Libera el modem. Si rotate_ip=True, dispara rotacion de IP en background."""
        ...

    async def report_failure(self, modem: Modem, reason: str) -> None:
        """Marca modem como UNHEALTHY si reason es transitorio o QUARANTINED si flagged."""
        ...

    async def list_all(self) -> list[Modem]:
        """Vista de todos los modems del pool (para health dashboards)."""
        ...

    async def list_available(self, *, country: Country | None = None) -> list[Modem]:
        """Modems READY con capacidad. Filtrable por pais."""
        ...

    async def reset_daily_counters(self) -> None:
        """Resetea contadores diarios. Llamar por cron a las 00:00 local del modem."""
        ...

    def stream_proxy_endpoints(
        self,
        *,
        country: Country | None = None,
    ) -> AsyncIterator[ProxyEndpoint]:
        """Iterador async de ProxyEndpoints disponibles. Conecta con IProxyProvider."""
        ...
