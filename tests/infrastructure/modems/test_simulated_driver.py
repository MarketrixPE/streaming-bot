"""Tests del driver simulado."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from structlog.stdlib import BoundLogger

from streaming_bot.domain.modem import Modem
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.modems.simulated_driver import SimulatedModemDriver


class TestSimulatedModemDriver:
    @pytest.fixture
    def driver(self, silent_logger: BoundLogger) -> SimulatedModemDriver:
        return SimulatedModemDriver(
            logger=silent_logger,
            health_check_failure_rate=0.0,
            seed=99,
        )

    async def test_health_check_succeeds_when_failure_rate_zero(
        self,
        driver: SimulatedModemDriver,
        make_modem: Callable[..., Modem],
    ) -> None:
        modem = make_modem(country=Country.PE)
        assert await driver.health_check(modem) is True

    async def test_rotate_ip_returns_country_consistent_ip(
        self,
        driver: SimulatedModemDriver,
        make_modem: Callable[..., Modem],
    ) -> None:
        modem = make_modem(country=Country.PE)
        ip = await driver.rotate_ip(modem)
        assert ip is not None
        assert ip.startswith(("190.117.", "200.123.", "181.65."))

    async def test_signal_strength_within_bounds(
        self,
        driver: SimulatedModemDriver,
        make_modem: Callable[..., Modem],
    ) -> None:
        modem = make_modem(country=Country.MX)
        for _ in range(20):
            dbm = await driver.get_signal_strength(modem)
            assert -95 <= dbm <= -65

    async def test_health_check_can_fail_with_nonzero_rate(
        self,
        silent_logger: BoundLogger,
        make_modem: Callable[..., Modem],
    ) -> None:
        # Failure rate=1.0 -> siempre False; valida la rama UNHEALTHY de la logica externa.
        driver = SimulatedModemDriver(
            logger=silent_logger,
            health_check_failure_rate=1.0,
            seed=1,
        )
        modem = make_modem(country=Country.US)
        assert await driver.health_check(modem) is False
