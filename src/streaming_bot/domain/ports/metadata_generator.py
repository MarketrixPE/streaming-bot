"""Puerto para enriquecer metadata via LLM (titulo, tags, descripcion)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from streaming_bot.domain.catalog_pipeline.metadata_pack import MetadataPack
from streaming_bot.domain.catalog_pipeline.raw_audio import RawAudio
from streaming_bot.domain.catalog_pipeline.track_brief import TrackBrief
from streaming_bot.domain.exceptions import DomainError


class MetadataGenerationError(DomainError):
    """Error tipado para fallos del puerto de enriquecido."""


@runtime_checkable
class IMetadataGenerator(Protocol):
    """Genera ``MetadataPack`` a partir de brief + audio masterizado."""

    async def enrich(
        self,
        brief: TrackBrief,
        raw: RawAudio,
        *,
        cover_art_path: Path,
    ) -> MetadataPack:
        """Devuelve metadata SEO/comercial ya completa.

        Args:
            brief: encargo creativo original.
            raw: pista masterizada.
            cover_art_path: ruta al PNG de portada (ya generado por
                ``ICoverArtGenerator``).
        """
        ...
