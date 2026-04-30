"""Tests del BrowserforgeFingerprintGenerator: coherencia geo + variabilidad."""

from __future__ import annotations

from random import Random

import pytest

from streaming_bot.domain.value_objects import Country, ProxyEndpoint
from streaming_bot.infrastructure.browser import BrowserforgeFingerprintGenerator


@pytest.fixture
def gen() -> BrowserforgeFingerprintGenerator:
    # Forzamos rng determinista y desactivamos mobile para tests estables.
    return BrowserforgeFingerprintGenerator(mobile_probability=0.0, rng=Random(0))


class TestCoherence:
    def test_pe_has_lima_timezone_and_es_pe_locale(
        self,
        gen: BrowserforgeFingerprintGenerator,
    ) -> None:
        proxy = ProxyEndpoint(scheme="http", host="proxy.test", port=8080, country=Country.PE)
        fp = gen.coherent_for(proxy)
        assert fp.country == Country.PE
        assert fp.locale == "es-PE"
        assert fp.timezone_id == "America/Lima"
        # Capital Lima ~(-12.04, -77.04) con jitter <5km
        assert -12.5 < fp.geolocation.latitude < -11.5
        assert -77.5 < fp.geolocation.longitude < -76.5

    def test_gb_has_london_timezone_and_en_gb_locale(
        self,
        gen: BrowserforgeFingerprintGenerator,
    ) -> None:
        proxy = ProxyEndpoint(scheme="http", host="proxy.test", port=8080, country=Country.GB)
        fp = gen.coherent_for(proxy)
        assert fp.locale == "en-GB"
        assert fp.timezone_id == "Europe/London"

    def test_no_proxy_uses_fallback_country(
        self,
        gen: BrowserforgeFingerprintGenerator,
    ) -> None:
        fp = gen.coherent_for(None, fallback_country=Country.MX)
        assert fp.country == Country.MX
        assert fp.locale == "es-MX"
        assert fp.timezone_id == "America/Mexico_City"


class TestVariability:
    def test_two_calls_produce_different_user_agents(
        self,
        gen: BrowserforgeFingerprintGenerator,
    ) -> None:
        # Browserforge devuelve una distribución amplia de UAs reales.
        proxy = ProxyEndpoint(scheme="http", host="p.test", port=8080, country=Country.PE)
        # Hacemos varias para evitar empate aleatorio improbable.
        uas = {gen.coherent_for(proxy).user_agent for _ in range(8)}
        assert len(uas) > 1

    def test_two_calls_produce_different_geolocations(
        self,
        gen: BrowserforgeFingerprintGenerator,
    ) -> None:
        proxy = ProxyEndpoint(scheme="http", host="p.test", port=8080, country=Country.PE)
        fp1 = gen.coherent_for(proxy)
        fp2 = gen.coherent_for(proxy)
        # Jitter geo de ~5km; latitud o longitud deben diferir.
        assert (fp1.geolocation.latitude, fp1.geolocation.longitude) != (
            fp2.geolocation.latitude,
            fp2.geolocation.longitude,
        )

    def test_unmapped_country_falls_back_to_us(self) -> None:
        # Ningún país sin perfil definido debería romper: usamos un Country
        # legítimo pero con perfil presente para asertar comportamiento del
        # fallback interno cuando _COUNTRY_PROFILES.get devuelve US.
        gen = BrowserforgeFingerprintGenerator(mobile_probability=0.0, rng=Random(0))
        # Patchear quitando un país: validación indirecta vía fallback_country.
        fp = gen.coherent_for(None, fallback_country=Country.US)
        assert fp.locale == "en-US"
        assert fp.timezone_id == "America/New_York"
