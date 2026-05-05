"""Adapters de infraestructura del pipeline de catalogo AI."""

from streaming_bot.infrastructure.catalog_pipeline.dalle_cover_generator import (
    DalleCoverGenerator,
)
from streaming_bot.infrastructure.catalog_pipeline.ffmpeg_mastering import (
    FfmpegAudioMastering,
)
from streaming_bot.infrastructure.catalog_pipeline.local_storage import (
    LocalRawAudioStorage,
)
from streaming_bot.infrastructure.catalog_pipeline.openai_metadata_generator import (
    OpenAIMetadataGenerator,
)
from streaming_bot.infrastructure.catalog_pipeline.suno_generator import SunoGenerator
from streaming_bot.infrastructure.catalog_pipeline.udio_generator import UdioGenerator

__all__ = [
    "DalleCoverGenerator",
    "FfmpegAudioMastering",
    "LocalRawAudioStorage",
    "OpenAIMetadataGenerator",
    "SunoGenerator",
    "UdioGenerator",
]
