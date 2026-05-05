"""Puerto para generar portadas con IA de imagenes (DALL-E, Flux, etc.)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from streaming_bot.domain.catalog_pipeline.track_brief import TrackBrief
from streaming_bot.domain.exceptions import DomainError


class CoverArtGenerationError(DomainError):
    """Error tipado para fallos generando portada."""


@runtime_checkable
class ICoverArtGenerator(Protocol):
    """Genera una portada (3000x3000 PNG) acorde al brief.

    El `track_id` se usa como nombre canonico del archivo en el storage para
    asegurar idempotencia.
    """

    async def generate(self, brief: TrackBrief, *, track_id: str) -> Path:
        """Devuelve la ruta canonica al PNG generado."""
        ...
