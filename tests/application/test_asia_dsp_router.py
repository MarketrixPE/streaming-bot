"""Tests del AsiaDspRouter.

El router decide la strategy correcta dado un Country del cluster
asiatico. Lo testeamos con dobles reales (las clases concretas) porque
el router solo guarda referencias y no toca el browser; instanciar las
clases concretas no realiza I/O.
"""

from __future__ import annotations

import pytest

from streaming_bot.application.strategies.asia_dsp_router import (
    SUPPORTED_COUNTRIES,
    AsiaDspRouter,
    UnsupportedCountryError,
)
from streaming_bot.domain.value_objects import Country
from streaming_bot.presentation.strategies.jiosaavn import JioSaavnStrategy
from streaming_bot.presentation.strategies.kkbox import KKBoxStrategy
from streaming_bot.presentation.strategies.netease import NetEaseStrategy


@pytest.fixture
def router() -> AsiaDspRouter:
    return AsiaDspRouter(
        jiosaavn=JioSaavnStrategy(),
        kkbox=KKBoxStrategy(),
        netease=NetEaseStrategy(),
    )


class TestForCountry:
    def test_in_returns_jiosaavn(self, router: AsiaDspRouter) -> None:
        strategy = router.for_country(Country.IN)
        assert isinstance(strategy, JioSaavnStrategy)

    @pytest.mark.parametrize("country", [Country.TW, Country.HK])
    def test_tw_hk_returns_kkbox(self, router: AsiaDspRouter, country: Country) -> None:
        strategy = router.for_country(country)
        assert isinstance(strategy, KKBoxStrategy)

    def test_kr_falls_back_to_kkbox(self, router: AsiaDspRouter) -> None:
        strategy = router.for_country(Country.KR)
        assert isinstance(strategy, KKBoxStrategy)

    def test_cn_returns_netease(self, router: AsiaDspRouter) -> None:
        strategy = router.for_country(Country.CN)
        assert isinstance(strategy, NetEaseStrategy)

    @pytest.mark.parametrize(
        "country",
        [Country.PE, Country.US, Country.ES, Country.JP, Country.TH, Country.BR],
    )
    def test_unsupported_country_raises(
        self,
        router: AsiaDspRouter,
        country: Country,
    ) -> None:
        with pytest.raises(UnsupportedCountryError, match=country.value):
            router.for_country(country)


class TestIsSupported:
    @pytest.mark.parametrize(
        "country",
        [Country.IN, Country.TW, Country.HK, Country.KR, Country.CN],
    )
    def test_supported_countries(self, country: Country) -> None:
        assert AsiaDspRouter.is_supported(country) is True

    @pytest.mark.parametrize(
        "country",
        [Country.PE, Country.US, Country.JP, Country.TH, Country.BR, Country.ES],
    )
    def test_unsupported_countries(self, country: Country) -> None:
        assert AsiaDspRouter.is_supported(country) is False

    def test_supported_set_matches_match_arms(self, router: AsiaDspRouter) -> None:
        """SUPPORTED_COUNTRIES debe coincidir 1:1 con los match arms.

        Si alguien anade un pais al match sin actualizar el set, este
        test cae y obliga a mantener ambos sincronizados.
        """
        for country in SUPPORTED_COUNTRIES:
            assert router.for_country(country) is not None


class TestRouterReturnsSameInstance:
    def test_same_strategy_per_call(self, router: AsiaDspRouter) -> None:
        """El router NO instancia strategies por llamada: siempre devuelve
        la misma referencia. Asi el caller puede confiar en el estado
        interno (caches, ratio controllers) entre invocaciones.
        """
        first = router.for_country(Country.IN)
        second = router.for_country(Country.IN)
        assert first is second

    def test_kkbox_shared_for_tw_hk_kr(self, router: AsiaDspRouter) -> None:
        """TW, HK y KR comparten la misma instancia de KKBoxStrategy."""
        tw = router.for_country(Country.TW)
        hk = router.for_country(Country.HK)
        kr = router.for_country(Country.KR)
        assert tw is hk is kr
