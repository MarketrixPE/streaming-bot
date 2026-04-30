"""Tests del adapter ModemPoolProxyProvider sobre IProxyProvider."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from structlog.stdlib import BoundLogger

from streaming_bot.domain.modem import Modem, ModemState
from streaming_bot.domain.value_objects import Country, ProxyEndpoint
from streaming_bot.infrastructure.modems.interface_binder import LinuxInterfaceBinder
from streaming_bot.infrastructure.modems.local_proxy_runner import DanteProxyRunner
from streaming_bot.infrastructure.modems.modem_pool import ModemPool
from streaming_bot.infrastructure.modems.modem_proxy_provider import ModemPoolProxyProvider
from streaming_bot.infrastructure.modems.simulated_driver import SimulatedModemDriver

from .conftest import InMemoryModemRepository


@pytest.fixture
def provider_factory(
    silent_logger: BoundLogger,
    in_memory_modem_repo: InMemoryModemRepository,
) -> Callable[[list[Modem]], tuple[ModemPoolProxyProvider, ModemPool]]:
    def _factory(modems: list[Modem]) -> tuple[ModemPoolProxyProvider, ModemPool]:
        for modem in modems:
            in_memory_modem_repo._modems[modem.id] = modem
        driver = SimulatedModemDriver(
            logger=silent_logger,
            health_check_failure_rate=0.0,
            seed=11,
        )
        binder = LinuxInterfaceBinder(logger=silent_logger, fake_in_non_linux=True)
        runner = DanteProxyRunner(logger=silent_logger)
        pool = ModemPool(
            driver=driver,
            repository=in_memory_modem_repo,
            interface_binder=binder,
            proxy_runner=runner,
            logger=silent_logger,
        )
        provider = ModemPoolProxyProvider(pool=pool, logger=silent_logger)
        return provider, pool

    return _factory


class TestModemPoolProxyProvider:
    async def test_acquire_returns_endpoint_with_country(
        self,
        make_modem: Callable[..., Modem],
        provider_factory: Callable[
            [list[Modem]],
            tuple[ModemPoolProxyProvider, ModemPool],
        ],
    ) -> None:
        provider, _ = provider_factory([make_modem(country=Country.PE)])
        endpoint = await provider.acquire(country=Country.PE)
        assert endpoint is not None
        assert endpoint.scheme == "socks5"
        assert endpoint.country == Country.PE

    async def test_acquire_without_country_returns_none(
        self,
        make_modem: Callable[..., Modem],
        provider_factory: Callable[
            [list[Modem]],
            tuple[ModemPoolProxyProvider, ModemPool],
        ],
    ) -> None:
        provider, _ = provider_factory([make_modem(country=Country.PE)])
        # Country None -> no podemos elegir modem por geo coherente.
        assert await provider.acquire(country=None) is None

    async def test_report_failure_propagates_to_pool(
        self,
        make_modem: Callable[..., Modem],
        provider_factory: Callable[
            [list[Modem]],
            tuple[ModemPoolProxyProvider, ModemPool],
        ],
    ) -> None:
        modem = make_modem(country=Country.MX)
        provider, _pool = provider_factory([modem])
        endpoint = await provider.acquire(country=Country.MX)
        assert endpoint is not None
        await provider.report_failure(endpoint, "captcha shown")
        assert modem.state == ModemState.QUARANTINED

    async def test_report_success_releases_modem(
        self,
        make_modem: Callable[..., Modem],
        provider_factory: Callable[
            [list[Modem]],
            tuple[ModemPoolProxyProvider, ModemPool],
        ],
    ) -> None:
        modem = make_modem(country=Country.ES)
        provider, _pool = provider_factory([modem])
        endpoint = await provider.acquire(country=Country.ES)
        assert endpoint is not None
        await provider.report_success(endpoint)
        # release marca COOLING_DOWN.
        assert modem.state == ModemState.COOLING_DOWN

    async def test_report_failure_unknown_endpoint_is_safe(
        self,
        make_modem: Callable[..., Modem],
        provider_factory: Callable[
            [list[Modem]],
            tuple[ModemPoolProxyProvider, ModemPool],
        ],
    ) -> None:
        provider, _ = provider_factory([make_modem(country=Country.PE)])
        rogue = await provider.acquire(country=Country.PE)
        assert rogue is not None
        # Reportamos un endpoint inventado: el provider no debe romper.
        fake = ProxyEndpoint(scheme="socks5", host="127.0.0.1", port=65000)
        await provider.report_failure(fake, "timeout")
