"""``RawAudio``: referencia inmutable a un archivo de audio en disco.

El value object guarda metadatos tecnicos pero NO los bytes en memoria; la
ruta apunta al archivo persistido por la implementacion de
``IRawAudioStorage`` (filesystem, S3/MinIO, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable


class AudioFormat(str, Enum):
    """Formatos de audio soportados."""

    WAV = "wav"
    FLAC = "flac"
    MP3 = "mp3"


@dataclass(frozen=True, slots=True)
class RawAudio:
    """Referencia a un archivo de audio en almacenamiento.

    Atributos:
        bytes_path: ruta absoluta o relativa al archivo persistido.
        format: codec contenedor (wav/flac/mp3).
        sample_rate: muestras por segundo (Hz).
        duration_ms: duracion calculada en milisegundos.
    """

    bytes_path: Path
    format: AudioFormat
    sample_rate: int
    duration_ms: int

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError(f"sample_rate invalido: {self.sample_rate}")
        if self.duration_ms <= 0:
            raise ValueError(f"duration_ms invalido: {self.duration_ms}")

    def duration_seconds(self) -> int:
        return self.duration_ms // 1000


@runtime_checkable
class IRawAudioStorage(Protocol):
    """Puerto para persistir bytes de audio crudo o masterizado.

    Implementaciones tipicas: ``LocalFileStorage`` (filesystem), o un futuro
    ``S3Storage``/``MinIOStorage``.
    """

    async def save(
        self,
        data: bytes,
        *,
        track_id: str,
        audio_format: AudioFormat,
    ) -> Path:
        """Persiste ``data`` y devuelve la ruta canonica del archivo."""
        ...

    async def load(self, track_id: str, *, audio_format: AudioFormat) -> Path | None:
        """Devuelve la ruta de un track previamente guardado o ``None``."""
        ...
