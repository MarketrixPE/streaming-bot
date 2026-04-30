"""Modem fisico 4G/5G como recurso del pool de proxies residenciales.

Cada modem tiene una SIM (con su pais), un IMEI fingerprint, una IP publica
actual (rotable via reconexion), y un estado de salud. El pool reparte
modems entre cuentas activas garantizando coherencia geo (modem-PE para
cuenta-PE) y rate limits razonables (max-3-cuentas por modem por dia).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from uuid import uuid4

from streaming_bot.domain.value_objects import Country, ProxyEndpoint


class ModemState(str, Enum):
    """Estado operativo del modem."""

    READY = "ready"  # OK, puede aceptar trafico
    IN_USE = "in_use"  # asignado a una sesion activa
    ROTATING = "rotating"  # en proceso de reconexion (cambio IP)
    COOLING_DOWN = "cooling_down"  # pausa post-uso para evitar overheat
    UNHEALTHY = "unhealthy"  # falla de conectividad temporal
    QUARANTINED = "quarantined"  # IP/IMEI flagged, requiere reset profundo
    OFFLINE = "offline"  # sin senal, fisicamente desconectado


@dataclass(frozen=True, slots=True)
class ModemHardware:
    """Identidad fisica inmutable del modem."""

    imei: str
    iccid: str  # SIM identifier
    model: str  # ej "Quectel EG25-G"
    serial_port: str  # ej "/dev/ttyUSB2"
    operator: str  # ej "Movistar PE", "Claro MX"
    sim_country: Country


@dataclass(slots=True)
class Modem:
    """Modem 4G/5G individual del pool.

    Mutable controladamente: solo `IModemPool` debe llamar a metodos
    de transicion. Los handlers que usan el modem reciben una vista
    de solo-lectura (proxy + sim_country).
    """

    id: str
    hardware: ModemHardware
    state: ModemState = ModemState.READY
    current_public_ip: str | None = None
    last_rotation_at: datetime | None = None
    last_used_at: datetime | None = None
    last_health_check_at: datetime | None = None
    accounts_used_today: int = 0
    streams_served_today: int = 0
    flagged_count: int = 0
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Limites operativos
    max_accounts_per_day: int = 3
    max_streams_per_day: int = 250
    rotation_cooldown_seconds: int = 90
    use_cooldown_seconds: int = 300  # 5 min entre cuentas distintas

    @classmethod
    def new(cls, *, hardware: ModemHardware) -> Modem:
        return cls(id=str(uuid4()), hardware=hardware)

    @property
    def country(self) -> Country:
        return self.hardware.sim_country

    @property
    def is_available(self) -> bool:
        return self.state == ModemState.READY and self.has_capacity_today()

    def has_capacity_today(self) -> bool:
        return (
            self.accounts_used_today < self.max_accounts_per_day
            and self.streams_served_today < self.max_streams_per_day
        )

    def can_assign_now(self) -> bool:
        if not self.is_available:
            return False
        if self.last_used_at is None:
            return True
        elapsed = datetime.now(UTC) - self.last_used_at
        return elapsed >= timedelta(seconds=self.use_cooldown_seconds)

    def assign(self) -> None:
        if not self.is_available:
            raise ValueError(f"modem {self.id} no esta disponible (estado={self.state})")
        self.state = ModemState.IN_USE
        self.last_used_at = datetime.now(UTC)
        self.accounts_used_today += 1

    def release(self, *, streams_served: int = 0) -> None:
        if self.state != ModemState.IN_USE:
            raise ValueError(f"release de modem no en uso: {self.state}")
        self.state = ModemState.COOLING_DOWN
        self.streams_served_today += streams_served

    def begin_rotation(self) -> None:
        self.state = ModemState.ROTATING
        self.last_rotation_at = datetime.now(UTC)

    def complete_rotation(self, *, new_public_ip: str | None) -> None:
        self.current_public_ip = new_public_ip
        self.state = ModemState.READY

    def mark_unhealthy(self, reason: str) -> None:
        self.state = ModemState.UNHEALTHY
        self.notes = f"unhealthy:{reason}"

    def quarantine(self, reason: str) -> None:
        self.state = ModemState.QUARANTINED
        self.flagged_count += 1
        self.notes = f"quarantined:{reason}"

    def mark_ready(self) -> None:
        self.state = ModemState.READY

    def reset_daily_counters(self) -> None:
        self.accounts_used_today = 0
        self.streams_served_today = 0

    def to_proxy_endpoint(self, *, local_proxy_port: int) -> ProxyEndpoint:
        """Convierte el modem en un ProxyEndpoint que el browser puede usar.

        Asume que cada modem tiene un proxy local (3proxy/dante) escuchando
        en `local_proxy_port` que tunela trafico via la interfaz movil.
        """
        return ProxyEndpoint(
            scheme="socks5",
            host="127.0.0.1",
            port=local_proxy_port,
            country=self.hardware.sim_country,
        )
