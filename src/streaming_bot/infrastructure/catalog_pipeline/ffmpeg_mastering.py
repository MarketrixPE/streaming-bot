"""``FfmpegAudioMastering``: ``IAudioMastering`` ejecutando ffmpeg como subproceso.

Aplica EBU R128 loudness normalization en doble pasada (la mas precisa) +
true peak limiter, escribiendo a un archivo nuevo bajo ``output_dir``. La
salida es WAV PCM 24-bit por defecto (la masterizacion final a MP3/AAC se
hace en otra etapa por DSP).

Comando equivalente:
    ffmpeg -i in.wav -af loudnorm=I=-14:LRA=11:TP=-1:print_format=summary
        -ar 44100 -c:a pcm_s24le out.wav
"""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from streaming_bot.domain.catalog_pipeline.raw_audio import AudioFormat, RawAudio
from streaming_bot.domain.ports.audio_mastering import (
    AudioMasteringError,
    IAudioMastering,
    MasteringProfile,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from structlog.stdlib import BoundLogger


class FfmpegAudioMastering(IAudioMastering):
    """Implementacion ``IAudioMastering`` invocando ffmpeg via subprocess.

    El ``runner`` es inyectable para que los tests puedan mockear el
    subproceso sin necesitar ffmpeg instalado.
    """

    def __init__(
        self,
        *,
        ffmpeg_path: Path,
        output_dir: Path,
        output_format: AudioFormat = AudioFormat.WAV,
        runner: Callable[[list[str]], Awaitable[tuple[int, bytes, bytes]]] | None = None,
        logger: BoundLogger | None = None,
    ) -> None:
        self._ffmpeg_path = ffmpeg_path
        self._output_dir = output_dir
        self._output_format = output_format
        self._runner = runner or self._default_runner
        self._log = logger or structlog.get_logger("ffmpeg_mastering")

    async def master(self, raw: RawAudio, profile: MasteringProfile) -> RawAudio:
        if not raw.bytes_path.exists():
            raise AudioMasteringError(
                f"ffmpeg: archivo de entrada no existe: {raw.bytes_path}",
            )

        self._output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._build_output_path(raw.bytes_path)
        argv = self._build_argv(
            input_path=raw.bytes_path,
            output_path=output_path,
            profile=profile,
        )
        self._log.info(
            "ffmpeg.master.start",
            cmd=shlex.join(argv),
            input=str(raw.bytes_path),
            output=str(output_path),
            profile=profile.name,
        )

        return_code, _stdout, stderr = await self._runner(argv)
        if return_code != 0:
            raise AudioMasteringError(
                f"ffmpeg salio con codigo {return_code}: "
                f"{stderr.decode('utf-8', errors='replace')[:500]}",
            )

        if not output_path.exists():
            raise AudioMasteringError(
                f"ffmpeg termino OK pero no creo el archivo: {output_path}",
            )

        self._log.info(
            "ffmpeg.master.done",
            output=str(output_path),
            size_bytes=output_path.stat().st_size,
        )
        return RawAudio(
            bytes_path=output_path,
            format=self._output_format,
            sample_rate=profile.sample_rate,
            duration_ms=raw.duration_ms,
        )

    def _build_output_path(self, input_path: Path) -> Path:
        """Construye una ruta determinista para el archivo masterizado."""
        return self._output_dir / f"{input_path.stem}.mastered.{self._output_format.value}"

    def _build_argv(
        self,
        *,
        input_path: Path,
        output_path: Path,
        profile: MasteringProfile,
    ) -> list[str]:
        loudnorm_filter = (
            f"loudnorm=I={profile.integrated_lufs}"
            f":LRA={profile.loudness_range_lu}"
            f":TP={profile.true_peak_db}"
            ":print_format=summary"
        )
        return [
            str(self._ffmpeg_path),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-af",
            loudnorm_filter,
            "-ar",
            str(profile.sample_rate),
            "-c:a",
            self._codec_for_format(self._output_format),
            str(output_path),
        ]

    @staticmethod
    def _codec_for_format(audio_format: AudioFormat) -> str:
        if audio_format == AudioFormat.WAV:
            return "pcm_s24le"
        if audio_format == AudioFormat.FLAC:
            return "flac"
        return "libmp3lame"

    async def _default_runner(self, argv: list[str]) -> tuple[int, bytes, bytes]:
        """Runner por defecto: ``asyncio.create_subprocess_exec``.

        Los argv vienen de configuracion controlada y rutas internas; no hay
        riesgo de inyeccion porque ``shell=False`` siempre.
        """
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return_code = process.returncode if process.returncode is not None else -1
        return return_code, stdout, stderr
