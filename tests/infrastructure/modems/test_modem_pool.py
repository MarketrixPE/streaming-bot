"""Tests del ModemPool: acquire/release/cooldowns/cuotas/quarantine."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from structlog.stdlib import BoundLogger

from streaming_bot.domain.modem import Modem, ModemState
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.modems.interface_binder import LinuxInterfaceBinder
from streaming_bot.infrastructure.modems.local_proxy_runner import DanteProxyRunner
from streaming_bot.infrastructure.modems.modem_pool import ModemPool
from streaming_bot.infrastructure.modems.simulated_driver import SimulatedModemDriver

from .conftest import InMemoryModemRepository


@pytest.fixture
def pool_factory(
    silent_logger: BoundLogger,
    in_memory_modem_repo: InMemoryModemRepository,
) -> Callable[[list[Modem]], ModemPool]:
    """Factory: dado un set de modems, los persiste y construye un pool."""

    def _factory(modems: list[Modem]) -> ModemPool:
        for modem in modems:
            # repositorio in-memory: add es sync sobre dict, lo invocamos via run_until_complete
            # via asyncio mediante pytest-asyncio. Aqui basta con setear directamente.
            in_memory_modem_repo._modems[modem.id] = modem
        driver = SimulatedModemDriver(
            logger=silent_logger,
            health_check_failure_rate=0.0,
            seed=7,
        )
        binder = LinuxInterfaceBinder(logger=silent_logger, fake_in_non_linux=True)
        runner = DanteProxyRunner(logger=silent_logger)
        return ModemPool(
            driver=driver,
            repository=in_memory_modem_repo,
            interface_binder=binder,
            proxy_runner=runner,
            logger=silent_logger,
        )

    return _factory


class TestAcquire:
    async def test_returns_modem_of_requested_country(
        self,
        make_modem: Callable[..., Modem],
        pool_factory: Callable[[list[Modem]], ModemPool],
    ) -> None:
        modems = [
            make_modem(country=Country.PE, serial_port="/dev/ttyUSB0"),
            make_modem(country=Country.MX, serial_port="/dev/ttyUSB1"),
            make_modem(country=Country.ES, serial_port="/dev/ttyUSB2"),
        ]
        pool = pool_factory(modems)
        acquired = await pool.acquire(country=Country.MX)
        assert acquired is not None
        assert acquired.country == Country.MX
        assert acquired.state == ModemState.IN_USE

    async def test_timeout_returns_none_when_no_country_match(
        self,
        make_modem: Callable[..., Modem],
        pool_factory: Callable[[list[Modem]], ModemPool],
    ) -> None:
        # Solo modems PE en el pool: pedir DE debe retornar None tras timeout corto.
        pool = pool_factory([make_modem(country=Country.PE)])
        result = await pool.acquire(country=Country.DE, timeout_seconds=0.2)
        assert result is None

    async def test_respects_cooldown_between_assignments(
        self,
        make_modem: Callable[..., Modem],
        pool_factory: Callable[[list[Modem]], ModemPool],
    ) -> None:
        modems = [make_modem(country=Country.PE)]
        pool = pool_factory(modems)
        first = await pool.acquire(country=Country.PE)
        assert first is not None
        # Forzamos READY pero last_used_at reciente -> cooldown 5 min activo.
        first.state = ModemState.READY
        first.last_used_at = datetime.now(UTC)
        result = await pool.acquire(country=Country.PE, timeout_seconds=0.2)
        assert result is None

        # Movemos last_used_at >5 min al pasado -> debe poder asignarse.
        first.last_used_at = datetime.now(UTC) - timedelta(seconds=600)
        first.state = ModemState.READY
        # release del semaforo previo ya ocurrido por la transicion sintetica.
        # El semaforo del slot sigue tomado; lo soltamos explicitamente para simular release real.
        slot = pool._slots[first.id]
        if slot.semaphore.locked():
            slot.semaphore.release()
        again = await pool.acquire(country=Country.PE, timeout_seconds=0.2)
        assert again is not None
        assert again.id == first.id

    async def test_respects_max_accounts_per_day(
        self,
        make_modem: Callable[..., Modem],
        pool_factory: Callable[[list[Modem]], ModemPool],
    ) -> None:
        # max_accounts_per_day=3 por defecto; tras 3 asignaciones el modem agota su cuota.
        pool = pool_factory([make_modem(country=Country.PE)])
        for _ in range(3):
            modem = await pool.acquire(country=Country.PE, timeout_seconds=0.2)
            assert modem is not None
            await pool.release(modem, rotate_ip=False)
            # Reset artificial: simulamos que el modem volvio a READY tras rotar
            modem.state = ModemState.READY
            modem.last_used_at = datetime.now(UTC) - timedelta(seconds=600)
        # 4ta asignacion no debe ocurrir aunque haya capacidad temporal.
        result = await pool.acquire(country=Country.PE, timeout_seconds=0.2)
        assert result is None


class TestRelease:
    async def test_release_marks_cooling_down(
        self,
        make_modem: Callable[..., Modem],
        pool_factory: Callable[[list[Modem]], ModemPool],
    ) -> None:
        pool = pool_factory([make_modem(country=Country.PE)])
        modem = await pool.acquire(country=Country.PE)
        assert modem is not None
        await pool.release(modem, streams_served=42, rotate_ip=False)
        assert modem.state == ModemState.COOLING_DOWN
        assert modem.streams_served_today == 42


class TestReportFailure:
    async def test_captcha_quarantines(
        self,
        make_modem: Callable[..., Modem],
        pool_factory: Callable[[list[Modem]], ModemPool],
    ) -> None:
        pool = pool_factory([make_modem(country=Country.PE)])
        modem = await pool.acquire(country=Country.PE)
        assert modem is not None
        await pool.report_failure(modem, "captcha shown")
        assert modem.state == ModemState.QUARANTINED
        assert modem.flagged_count == 1

    async def test_timeout_marks_unhealthy(
        self,
        make_modem: Callable[..., Modem],
        pool_factory: Callable[[list[Modem]], ModemPool],
    ) -> None:
        pool = pool_factory([make_modem(country=Country.PE)])
        modem = await pool.acquire(country=Country.PE)
        assert modem is not None
        await pool.report_failure(modem, "request timeout")
        assert modem.state == ModemState.UNHEALTHY

    async def test_unknown_reason_defaults_to_unhealthy(
        self,
        make_modem: Callable[..., Modem],
        pool_factory: Callable[[list[Modem]], ModemPool],
    ) -> None:
        pool = pool_factory([make_modem(country=Country.PE)])
        modem = await pool.acquire(country=Country.PE)
        assert modem is not None
        await pool.report_failure(modem, "weird-undocumented-thing")
        # Fail-closed: marcamos UNHEALTHY antes que dejarlo READY con fallo silencioso.
        assert modem.state == ModemState.UNHEALTHY


class TestResetCounters:
    async def test_reset_daily_counters_clears_usage(
        self,
        make_modem: Callable[..., Modem],
        pool_factory: Callable[[list[Modem]], ModemPool],
    ) -> None:
        pool = pool_factory([make_modem(country=Country.PE)])
        modem = await pool.acquire(country=Country.PE)
        assert modem is not None
        await pool.release(modem, streams_served=10, rotate_ip=False)
        assert modem.accounts_used_today == 1
        assert modem.streams_served_today == 10
        await pool.reset_daily_counters()
        assert modem.accounts_used_today == 0
        assert modem.streams_served_today == 0


class TestProxyEndpointAssignment:
    async def test_to_proxy_endpoint_assigns_local_port(
        self,
        make_modem: Callable[..., Modem],
        pool_factory: Callable[[list[Modem]], ModemPool],
    ) -> None:
        modems = [
            make_modem(country=Country.PE, serial_port="/dev/ttyUSB0"),
            make_modem(country=Country.PE, serial_port="/dev/ttyUSB1"),
        ]
        pool = pool_factory(modems)
        first_endpoint = await pool.to_proxy_endpoint(modems[0])
        second_endpoint = await pool.to_proxy_endpoint(modems[1])
        assert first_endpoint.port != second_endpoint.port
        assert first_endpoint.scheme == "socks5"
        assert first_endpoint.host == "127.0.0.1"
        # Idempotencia: segunda llamada al mismo modem -> mismo puerto.
        again = await pool.to_proxy_endpoint(modems[0])
        assert again.port == first_endpoint.port
