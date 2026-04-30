"""Servicio de ingestión de camuflaje desde Spotify.

Refresca el pool de camuflaje desde charts/searches LATAM usando `ISpotifyClient`.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from streaming_bot.domain.ports.playlist_repo import ICamouflagePool
from streaming_bot.domain.value_objects import Country


@dataclass(frozen=True, slots=True)
class CamouflageIngestSummary:
    """Resultado de la ingestión de camuflaje."""

    markets_processed: int
    genres_per_market: int
    tracks_seen: int
    tracks_added: int
    tracks_updated: int
    errors: tuple[str, ...]


class CamouflageIngestService:
    """Servicio de ingestión de pool de camuflaje."""

    def __init__(
        self,
        camouflage_pool: ICamouflagePool,
        logger: structlog.BoundLogger | None = None,
    ) -> None:
        self._pool = camouflage_pool
        self._logger = logger or structlog.get_logger()

    async def refresh_for_markets(
        self,
        markets: list[Country],
    ) -> CamouflageIngestSummary:
        """Refresca el pool para los mercados indicados."""
        errors: list[str] = []
        markets_processed = 0

        self._logger.info(
            "refresh_for_markets_start",
            n_markets=len(markets),
            markets=[m.value for m in markets],
        )

        try:
            tracks_added = await self._pool.refresh_pool(markets=markets)
            markets_processed = len(markets)

            self._logger.info(
                "refresh_for_markets_complete",
                markets_processed=markets_processed,
                tracks_added=tracks_added,
            )

            return CamouflageIngestSummary(
                markets_processed=markets_processed,
                genres_per_market=6,  # _LATAM_GENRES
                tracks_seen=markets_processed * 6 * 50,  # estimate
                tracks_added=tracks_added,
                tracks_updated=0,
                errors=tuple(errors),
            )

        except Exception as exc:
            error_msg = f"refresh_pool_failed: {exc}"
            errors.append(error_msg)
            self._logger.error(
                "refresh_for_markets_error",
                error=str(exc),
                markets_processed=markets_processed,
            )

            return CamouflageIngestSummary(
                markets_processed=markets_processed,
                genres_per_market=6,
                tracks_seen=0,
                tracks_added=0,
                tracks_updated=0,
                errors=tuple(errors),
            )
