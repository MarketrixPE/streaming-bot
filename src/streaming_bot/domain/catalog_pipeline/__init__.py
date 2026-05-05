"""Pipeline de produccion de catalogo AI.

Conjunto de value objects inmutables que describen el flujo desde un brief
creativo hasta una pista lista para ser distribuida. Sin dependencias de I/O.
"""

from streaming_bot.domain.catalog_pipeline.metadata_pack import MetadataPack
from streaming_bot.domain.catalog_pipeline.raw_audio import (
    AudioFormat,
    IRawAudioStorage,
    RawAudio,
)
from streaming_bot.domain.catalog_pipeline.track_brief import TrackBrief

__all__ = [
    "AudioFormat",
    "IRawAudioStorage",
    "MetadataPack",
    "RawAudio",
    "TrackBrief",
]
