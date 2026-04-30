"""Tests para CamouflageIngestService."""

from __future__ import annotations

import pytest

from streaming_bot.application.camouflage import (
    CamouflageIngestService,
    CamouflageIngestSummary,
)
from streaming_bot.domain.playlist import PlaylistTrack
from streaming_bot.domain.value_objects import Country


class MockCamouflagePool:
    """Mock de ICamouflagePool para tests."""

    def __init__(self, should_fail: bool = False) -> None:
        self.refresh_called = False
        self.markets_received: list[Country] = []
        self.should_fail = should_fail

    async def refresh_pool(self, *, markets: list[Country]) -> int:
        """Mock de refresh_pool."""
        self.refresh_called = True
        self.markets_received = markets

        if self.should_fail:
            raise RuntimeError("Mocked refresh failure")

        return len(markets) * 10  # Simular 10 tracks por mercado

    async def fetch_top_by_genre(
        self,
        *,
        genre: str,
        market: Country,
        limit: int = 50,
    ) -> list[PlaylistTrack]:
        """Mock no usado en estos tests."""
        return []

    async def random_sample(
        self,
        *,
        market: Country,
        size: int,
        excluding_uris: set[str] | None = None,
    ) -> list[PlaylistTrack]:
        """Mock no usado en estos tests."""
        return []


@pytest.mark.asyncio
async def test_refresh_for_markets_calls_pool() -> None:
    """Verifica que el servicio llama al pool correctamente."""
    pool = MockCamouflagePool()
    service = CamouflageIngestService(pool)

    markets = [Country.PE, Country.MX, Country.US]
    summary = await service.refresh_for_markets(markets)

    assert pool.refresh_called
    assert pool.markets_received == markets
    assert summary.markets_processed == 3
    assert summary.tracks_added == 30  # 3 * 10
    assert len(summary.errors) == 0


@pytest.mark.asyncio
async def test_refresh_for_markets_handles_errors() -> None:
    """Verifica que captura excepciones y las reporta."""
    pool = MockCamouflagePool(should_fail=True)
    service = CamouflageIngestService(pool)

    markets = [Country.PE, Country.MX]
    summary = await service.refresh_for_markets(markets)

    assert summary.markets_processed == 0
    assert summary.tracks_added == 0
    assert len(summary.errors) > 0
    assert "refresh_pool_failed" in summary.errors[0]


@pytest.mark.asyncio
async def test_refresh_for_markets_returns_summary() -> None:
    """Verifica que devuelve un summary completo."""
    pool = MockCamouflagePool()
    service = CamouflageIngestService(pool)

    markets = [Country.PE]
    summary = await service.refresh_for_markets(markets)

    assert isinstance(summary, CamouflageIngestSummary)
    assert summary.markets_processed == 1
    assert summary.genres_per_market == 6  # _LATAM_GENRES
    assert summary.tracks_seen == 1 * 6 * 50  # estimate
    assert summary.tracks_added == 10
    assert summary.tracks_updated == 0
    assert isinstance(summary.errors, tuple)


@pytest.mark.asyncio
async def test_refresh_for_markets_with_empty_list() -> None:
    """Verifica que maneja lista vacía de mercados."""
    pool = MockCamouflagePool()
    service = CamouflageIngestService(pool)

    summary = await service.refresh_for_markets([])

    assert summary.markets_processed == 0
    assert summary.tracks_added == 0
