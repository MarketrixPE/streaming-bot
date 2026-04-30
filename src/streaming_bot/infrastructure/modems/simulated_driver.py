"""Driver de modem simulado en memoria para tests y dev local.

No abre puertos serial ni hace HTTP. Mantiene estado por modem.id:
- IP publica (rotada con valores aleatorios "creibles" por pais).
- Senal (RSSI fluctuando entre -65 y -95 dBm).
- Probabilidad configurable de fallo en health_check (5% por defecto).

Las decisiones aleatorias se hacen con un random.Random sembrado por modem.id
para que los tests sean reproducibles si el repo de modems es estable.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from streaming_bot.domain.modem import Modem
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.modems.at_commands import AT_PING, AT_RESET

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

# Rangos de IP publica creibles por pais (subnets reales del carrier dominante).
# Solo se usan para que los tests vean IPs distintas-pero-coherentes con la SIM.
_COUNTRY_IP_PREFIXES: dict[Country, tuple[str, ...]] = {
    Country.PE: ("190.117.", "200.123.", "181.65."),
    Country.MX: ("189.203.", "201.146.", "187.155."),
    Country.US: ("174.198.", "172.58.", "108.65."),
    Country.ES: ("83.36.", "85.52.", "88.18."),
    Country.AR: ("181.30.", "190.55.", "186.130."),
    Country.CO: ("181.49.", "190.27.", "186.30."),
    Country.CL: ("190.46.", "200.68.", "181.43."),
    Country.BR: ("177.32.", "189.6.", "201.86."),
}
_GENERIC_PREFIX: str = "203.0."

_SIMULATED_LATENCY_S: float = 0.005  # solo para "ceder" el loop sin frenar tests
_SIGNAL_DBM_MIN: int = -95
_SIGNAL_DBM_MAX: int = -65


@dataclass(slots=True)
class _SimulatedState:
    public_ip: str
    signal_dbm: int
    rng: random.Random
    at_history: list[str] = field(default_factory=list)


class SimulatedModemDriver:
    """Driver in-memory para tests / dev. Implementa IModemDriver."""

    def __init__(
        self,
        *,
        logger: BoundLogger,
        health_check_failure_rate: float = 0.05,
        seed: int | None = None,
    ) -> None:
        self._logger = logger
        self._failure_rate = health_check_failure_rate
        self._seed = seed
        self._states: dict[str, _SimulatedState] = {}
        self._lock = asyncio.Lock()

    async def health_check(self, modem: Modem) -> bool:
        # Asincronamente: el 5% por defecto devuelve False para ejercitar UNHEALTHY.
        await asyncio.sleep(_SIMULATED_LATENCY_S)
        state = await self._get_or_init_state(modem)
        roll = state.rng.random()
        healthy = roll >= self._failure_rate
        self._logger.debug("simulated_health_check", modem_id=modem.id, healthy=healthy)
        return healthy

    async def rotate_ip(self, modem: Modem) -> str | None:
        await asyncio.sleep(_SIMULATED_LATENCY_S)
        state = await self._get_or_init_state(modem)
        new_ip = _generate_country_ip(modem.country, state.rng)
        state.public_ip = new_ip
        self._logger.info("simulated_rotate_ip", modem_id=modem.id, new_ip=new_ip)
        return new_ip

    async def get_public_ip(self, modem: Modem) -> str | None:
        await asyncio.sleep(_SIMULATED_LATENCY_S)
        state = await self._get_or_init_state(modem)
        return state.public_ip

    async def get_signal_strength(self, modem: Modem) -> int:
        await asyncio.sleep(_SIMULATED_LATENCY_S)
        state = await self._get_or_init_state(modem)
        # Pequena fluctuacion alrededor del valor base para parecer real.
        delta = state.rng.randint(-3, 3)
        return max(_SIGNAL_DBM_MIN, min(_SIGNAL_DBM_MAX, state.signal_dbm + delta))

    async def reset(self, modem: Modem) -> None:
        await asyncio.sleep(_SIMULATED_LATENCY_S)
        async with self._lock:
            self._states.pop(modem.id, None)
        self._logger.info("simulated_reset", modem_id=modem.id)

    async def send_at_command(self, modem: Modem, command: str) -> str:
        await asyncio.sleep(_SIMULATED_LATENCY_S)
        state = await self._get_or_init_state(modem)
        state.at_history.append(command)
        if command == AT_PING:
            return f"{command}\nOK"
        if command == AT_RESET:
            return "OK"
        # Devolvemos un OK generico; los tests que requieran parsing usan parsers reales.
        return f"{command}\nOK"

    @property
    def at_history(self) -> dict[str, list[str]]:
        """Historico de comandos AT por modem (solo para tests)."""
        return {modem_id: list(state.at_history) for modem_id, state in self._states.items()}

    async def _get_or_init_state(self, modem: Modem) -> _SimulatedState:
        async with self._lock:
            existing = self._states.get(modem.id)
            if existing is not None:
                return existing
            seed_source = (self._seed or 0) ^ hash(modem.id)
            rng = random.Random(seed_source)  # noqa: S311 - no-cripto, reproducibilidad de tests
            state = _SimulatedState(
                public_ip=_generate_country_ip(modem.country, rng),
                signal_dbm=rng.randint(_SIGNAL_DBM_MIN, _SIGNAL_DBM_MAX),
                rng=rng,
            )
            self._states[modem.id] = state
            return state


def _generate_country_ip(country: Country, rng: random.Random) -> str:
    """Devuelve una IPv4 creible para el pais del modem."""
    prefixes = _COUNTRY_IP_PREFIXES.get(country)
    prefix = rng.choice(prefixes) if prefixes else _GENERIC_PREFIX
    return f"{prefix}{rng.randint(0, 255)}.{rng.randint(1, 254)}"
