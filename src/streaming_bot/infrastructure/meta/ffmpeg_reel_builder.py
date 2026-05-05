"""``FfmpegReelBuilder``: combina stock_video + audio + watermark en .mp4 9:16.

Comando ffmpeg base:

    ffmpeg -y -i $stock_video -i $audio_track \\
        -map 0:v -map 1:a -c:v libx264 -preset veryfast -crf 23 \\
        -c:a aac -shortest -t 30 \\
        -metadata comment="artist_uri=$artist_uri" \\
        -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" \\
        $output.mp4

Notas:
- Vertical 1080x1920 (Reels canonico). El crop centra el frame.
- Reescribimos el video para insertar el watermark via metadata (clave para
  tracking aguas abajo: si Meta filtrea el reel, el ``comment`` queda).
- ``-shortest -t 30`` corta a la duracion del audio o a 30s, lo que ocurra
  primero (Reels limit Q3 2025: 90s, pero 30s tiene mejor reach Q1 2026).
- El runner es inyectable para testing sin ffmpeg instalado.
"""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from streaming_bot.domain.exceptions import TransientError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from structlog.stdlib import BoundLogger


class ReelBuildError(TransientError):
    """Fallo al ejecutar ffmpeg para construir el Reel."""


class FfmpegReelBuilder:
    """Implementacion de ``IReelBuilder`` invocando ffmpeg via subprocess."""

    def __init__(
        self,
        *,
        ffmpeg_path: Path,
        runner: Callable[[list[str]], Awaitable[tuple[int, bytes, bytes]]] | None = None,
        max_duration_seconds: int = 30,
        target_width: int = 1080,
        target_height: int = 1920,
        logger: BoundLogger | None = None,
    ) -> None:
        self._ffmpeg = ffmpeg_path
        self._runner = runner or self._default_runner
        self._max_duration = max_duration_seconds
        self._target_width = target_width
        self._target_height = target_height
        self._log: BoundLogger = logger or structlog.get_logger("meta.ffmpeg_reel")

    async def build(
        self,
        *,
        stock_video_path: Path,
        audio_track_path: Path,
        output_path: Path,
        artist_uri: str,
        max_seconds: int = 30,
    ) -> Path:
        if not stock_video_path.exists():  # noqa: ASYNC240 - chequeo barato de existencia
            raise ReelBuildError(f"stock_video no existe: {stock_video_path}")
        if not audio_track_path.exists():  # noqa: ASYNC240 - chequeo barato de existencia
            raise ReelBuildError(f"audio_track no existe: {audio_track_path}")
        if not artist_uri:
            raise ReelBuildError("artist_uri vacio (necesario para watermark metadata)")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration = min(max_seconds, self._max_duration)

        argv = self._build_argv(
            stock_video_path=stock_video_path,
            audio_track_path=audio_track_path,
            output_path=output_path,
            artist_uri=artist_uri,
            duration=duration,
        )
        self._log.info(
            "reel_builder.start",
            cmd=shlex.join(argv),
            output=str(output_path),
            duration_s=duration,
        )

        return_code, _stdout, stderr = await self._runner(argv)
        if return_code != 0:
            raise ReelBuildError(
                f"ffmpeg salio con codigo {return_code}: "
                f"{stderr.decode('utf-8', errors='replace')[:500]}",
            )
        if not output_path.exists():  # noqa: ASYNC240 - validacion post-subprocess
            raise ReelBuildError(
                f"ffmpeg termino OK pero no creo el archivo: {output_path}",
            )

        self._log.info(
            "reel_builder.done",
            output=str(output_path),
            size_bytes=output_path.stat().st_size,  # noqa: ASYNC240 - stat local
        )
        return output_path

    def _build_argv(
        self,
        *,
        stock_video_path: Path,
        audio_track_path: Path,
        output_path: Path,
        artist_uri: str,
        duration: int,
    ) -> list[str]:
        scale_crop = (
            f"scale={self._target_width}:{self._target_height}"
            ":force_original_aspect_ratio=increase,"
            f"crop={self._target_width}:{self._target_height}"
        )
        return [
            str(self._ffmpeg),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(stock_video_path),
            "-i",
            str(audio_track_path),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-t",
            str(duration),
            "-metadata",
            f"comment=artist_uri={artist_uri}",
            "-vf",
            scale_crop,
            str(output_path),
        ]

    async def _default_runner(self, argv: list[str]) -> tuple[int, bytes, bytes]:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return_code = process.returncode if process.returncode is not None else -1
        return return_code, stdout, stderr
