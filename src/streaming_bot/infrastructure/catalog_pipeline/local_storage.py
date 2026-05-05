"""``LocalRawAudioStorage``: implementacion ``IRawAudioStorage`` sobre filesystem.

Persiste los bytes en ``{base_dir}/{track_id}.{ext}``. Crea la carpeta si no
existe. Es la opcion por defecto en desarrollo; un futuro adapter S3/MinIO
puede sustituirla sin tocar la capa de aplicacion.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import structlog

from streaming_bot.domain.catalog_pipeline.raw_audio import (
    AudioFormat,
    IRawAudioStorage,
)

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger


class LocalRawAudioStorage(IRawAudioStorage):
    """Guarda bytes en filesystem local con nombres ``track_id.ext``."""

    def __init__(
        self,
        *,
        base_dir: Path,
        logger: BoundLogger | None = None,
    ) -> None:
        self._base_dir = base_dir
        self._log = logger or structlog.get_logger("local_raw_audio_storage")

    async def save(
        self,
        data: bytes,
        *,
        track_id: str,
        audio_format: AudioFormat,
    ) -> Path:
        path = self._path_for(track_id, audio_format)
        await anyio.Path(self._base_dir).mkdir(parents=True, exist_ok=True)
        await anyio.Path(path).write_bytes(data)
        self._log.info(
            "raw_audio.saved",
            track_id=track_id,
            path=str(path),
            size_bytes=len(data),
        )
        return path

    async def load(self, track_id: str, *, audio_format: AudioFormat) -> Path | None:
        path = self._path_for(track_id, audio_format)
        if await anyio.Path(path).exists():
            return path
        return None

    def _path_for(self, track_id: str, audio_format: AudioFormat) -> Path:
        return self._base_dir / f"{track_id}.{audio_format.value}"
