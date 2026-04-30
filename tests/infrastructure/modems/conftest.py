"""Fixtures compartidos para tests de la capa modems.

Incluye:
- `silent_logger`: BoundLogger de structlog que descarta todo (no ensucia el output).
- `in_memory_modem_repo`: implementacion in-memory de IModemRepository.
- `make_modem` factory: helper para construir modems de prueba.
- `make_pool` factory: helper para construir un ModemPool con dependencies fakes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest
import structlog
from structlog.stdlib import BoundLogger

from streaming_bot.domain.modem import Modem, ModemHardware
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.modems.interface_binder import LinuxInterfaceBinder
from streaming_bot.infrastructure.modems.local_proxy_runner import DanteProxyRunner
from streaming_bot.infrastructure.modems.modem_pool import ModemPool
from streaming_bot.infrastructure.modems.simulated_driver import SimulatedModemDriver

if TYPE_CHECKING:
    from streaming_bot.domain.ports.modem_repo import IModemRepository


class InMemoryModemRepository:
    """Implementacion in-memory de IModemRepository para tests."""

    def __init__(self) -> None:
        self._modems: dict[str, Modem] = {}

    async def get(self, modem_id: str) -> Modem | None:
        return self._modems.get(modem_id)

    async def add(self, modem: Modem) -> None:
        self._modems[modem.id] = modem

    async def update(self, modem: Modem) -> None:
        self._modems[modem.id] = modem

    async def list_all(self) -> list[Modem]:
        return list(self._modems.values())

    async def list_by_country(self, country: Country) -> list[Modem]:
        return [m for m in self._modems.values() if m.country == country]


@pytest.fixture
def silent_logger() -> BoundLogger:
    """Logger silencioso para no ensuciar el output de tests (filtra < CRITICAL)."""
    structlog.configure(
        processors=[structlog.processors.KeyValueRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(50),
    )
    logger: BoundLogger = structlog.get_logger("tests.modems")
    return logger


@pytest.fixture
def in_memory_modem_repo() -> InMemoryModemRepository:
    return InMemoryModemRepository()


@pytest.fixture
def make_modem() -> Callable[..., Modem]:
    """Factory para construir un Modem de prueba con valores razonables."""

    def _factory(
        *,
        country: Country = Country.PE,
        serial_port: str = "/dev/ttyUSB0",
        operator: str = "Movistar PE",
        imei: str | None = None,
    ) -> Modem:
        hw = ModemHardware(
            imei=imei or "123456789012345",
            iccid="8951010" + "1" * 13,
            model="Quectel EG25-G",
            serial_port=serial_port,
            operator=operator,
            sim_country=country,
        )
        return Modem.new(hardware=hw)

    return _factory


@pytest.fixture
async def populated_pool(
    silent_logger: BoundLogger,
    in_memory_modem_repo: InMemoryModemRepository,
    make_modem: Callable[..., Modem],
) -> tuple[ModemPool, IModemRepository, list[Modem]]:
    """Pool con 3 modems PE + 1 MX + 1 ES. Ningun background task arrancado."""
    modems = [
        make_modem(country=Country.PE, serial_port="/dev/ttyUSB0", imei="111111111111111"),
        make_modem(country=Country.PE, serial_port="/dev/ttyUSB1", imei="222222222222222"),
        make_modem(country=Country.PE, serial_port="/dev/ttyUSB2", imei="333333333333333"),
        make_modem(country=Country.MX, serial_port="/dev/ttyUSB3", imei="444444444444444"),
        make_modem(country=Country.ES, serial_port="/dev/ttyUSB4", imei="555555555555555"),
    ]
    for modem in modems:
        await in_memory_modem_repo.add(modem)

    driver = SimulatedModemDriver(logger=silent_logger, health_check_failure_rate=0.0, seed=42)
    binder = LinuxInterfaceBinder(logger=silent_logger, fake_in_non_linux=True)
    runner = DanteProxyRunner(logger=silent_logger)
    pool = ModemPool(
        driver=driver,
        repository=in_memory_modem_repo,
        interface_binder=binder,
        proxy_runner=runner,
        logger=silent_logger,
    )
    await pool.load_from_repository()
    return pool, in_memory_modem_repo, modems
