"""Tests del proxy pool: parsing, scoring, cuarentena."""

from __future__ import annotations

from pathlib import Path

import pytest

from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.proxies import NoProxyProvider, StaticFileProxyProvider


class TestNoProxyProvider:
    async def test_acquire_returns_none(self) -> None:
        provider = NoProxyProvider()
        assert await provider.acquire() is None
        assert await provider.acquire(country=Country.ES) is None


class TestStaticFileProxyProvider:
    @pytest.fixture
    def provider(self, tmp_path: Path) -> StaticFileProxyProvider:
        proxy_file = tmp_path / "proxies.txt"
        proxy_file.write_text(
            "# comentario ignorado\n"
            "http://1.2.3.4:8080#country=ES\n"
            "socks5://user:pass@10.0.0.1:1080#country=DE\n"
            "https://example.com:443\n",
        )
        return StaticFileProxyProvider(
            path=proxy_file,
            healthcheck_url="https://api.ipify.org",
        )

    @pytest.fixture
    def provider_only_es(self, tmp_path: Path) -> StaticFileProxyProvider:
        """Provider con un único proxy taggeado a ES (sin fallback genérico)."""
        proxy_file = tmp_path / "proxies.txt"
        proxy_file.write_text("http://1.2.3.4:8080#country=ES\n")
        return StaticFileProxyProvider(
            path=proxy_file,
            healthcheck_url="https://api.ipify.org",
        )

    async def test_filters_by_country(self, provider: StaticFileProxyProvider) -> None:
        proxy = await provider.acquire(country=Country.ES)
        assert proxy is not None
        assert proxy.host == "1.2.3.4"
        assert proxy.country == Country.ES

    async def test_returns_proxy_without_country_when_country_filtered(
        self,
        provider: StaticFileProxyProvider,
    ) -> None:
        # FR no está en el archivo pero el proxy sin country debe ser elegible
        proxy = await provider.acquire(country=Country.FR)
        assert proxy is not None
        assert proxy.host == "example.com"

    async def test_quarantine_after_3_failures(
        self,
        provider_only_es: StaticFileProxyProvider,
    ) -> None:
        proxy = await provider_only_es.acquire(country=Country.ES)
        assert proxy is not None

        for _ in range(3):
            await provider_only_es.report_failure(proxy, reason="boom")

        # Tras 3 fallos, el único proxy ES queda en cuarentena
        proxy_again = await provider_only_es.acquire(country=Country.ES)
        assert proxy_again is None

    async def test_generic_proxy_used_when_country_specific_quarantined(
        self,
        provider: StaticFileProxyProvider,
    ) -> None:
        es_proxy = await provider.acquire(country=Country.ES)
        assert es_proxy is not None and es_proxy.country == Country.ES

        for _ in range(3):
            await provider.report_failure(es_proxy, reason="boom")

        # Cae al proxy genérico (sin country) como fallback
        fallback = await provider.acquire(country=Country.ES)
        assert fallback is not None
        assert fallback.country is None
