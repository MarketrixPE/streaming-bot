"""Tests del fingerprint coherente. Verifica que NO hay incoherencias como
las del bot original (proxy ES + timezone Antarctica/Vostok + locale ja-JP).
"""

from __future__ import annotations

import pytest

from streaming_bot.domain.value_objects import Country, ProxyEndpoint
from streaming_bot.infrastructure.fingerprints import CoherentFingerprintGenerator


@pytest.fixture
def gen() -> CoherentFingerprintGenerator:
    return CoherentFingerprintGenerator()


@pytest.mark.parametrize(
    ("country", "expected_tz_prefix", "expected_locale"),
    [
        (Country.ES, "Europe/Madrid", "es-ES"),
        (Country.DE, "Europe/Berlin", "de-DE"),
        (Country.JP, "Asia/Tokyo", "ja-JP"),
        (Country.BR, "America/Sao_Paulo", "pt-BR"),
        (Country.MX, "America/Mexico_City", "es-MX"),
    ],
)
def test_country_locale_timezone_are_coherent(
    gen: CoherentFingerprintGenerator,
    country: Country,
    expected_tz_prefix: str,
    expected_locale: str,
) -> None:
    proxy = ProxyEndpoint(scheme="http", host="x", port=80, country=country)
    fp = gen.coherent_for(proxy)
    assert fp.country == country
    assert fp.timezone_id == expected_tz_prefix
    assert fp.locale == expected_locale


def test_geolocation_jitter_within_radius(gen: CoherentFingerprintGenerator) -> None:
    proxy = ProxyEndpoint(scheme="http", host="x", port=80, country=Country.ES)
    fps = [gen.coherent_for(proxy) for _ in range(20)]
    # Deben estar cerca de Madrid (40.41, -3.70) ± ~5 km (~0.045°)
    for fp in fps:
        assert abs(fp.geolocation.latitude - 40.4168) < 0.1
        assert abs(fp.geolocation.longitude - (-3.7038)) < 0.1
    # Pero no todos exactamente iguales
    unique = {(fp.geolocation.latitude, fp.geolocation.longitude) for fp in fps}
    assert len(unique) > 1, "el jitter no está aleatorizando"


def test_no_proxy_uses_fallback(gen: CoherentFingerprintGenerator) -> None:
    fp = gen.coherent_for(None, fallback_country=Country.GB)
    assert fp.country == Country.GB
    assert fp.locale == "en-GB"
    assert fp.timezone_id == "Europe/London"


def test_user_agents_are_modern(gen: CoherentFingerprintGenerator) -> None:
    """Anti-regresion: el bot original usaba Chrome 94 (obsoleto).

    Tras el refactor del Mes 1 el pool por OS incluye Chrome 129-131 + Firefox
    130-131 + Safari 18.0/18.1 (refrescable trimestralmente). Cualquiera de
    esos cuenta como "moderno" siempre que NO sea Chrome/94.
    """
    samples = [gen.coherent_for(None) for _ in range(50)]
    modern_tokens = (
        "Chrome/129",
        "Chrome/130",
        "Chrome/131",
        "Firefox/130",
        "Firefox/131",
        "Version/18.0",
        "Version/18.1",
    )
    for fp in samples:
        assert "Chrome/94" not in fp.user_agent
        assert any(token in fp.user_agent for token in modern_tokens), (
            f"UA fuera del pool moderno: {fp.user_agent}"
        )
