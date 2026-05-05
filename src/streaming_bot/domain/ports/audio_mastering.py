"""Puerto para masterizado de audio.

Define el contrato del proceso de loudness normalization (EBU R128) y
limitado de true peak. El `MasteringProfile` es un value object configurable
por DSP (cada plataforma tiene su target):

- Spotify, Tidal, YouTube, Amazon Music: -14 LUFS / -1 dBTP.
- Apple Music: -16 LUFS / -1 dBTP (Sound Check ON).
- Podcasts (Apple Podcasts, Spotify): -16 LUFS / -1 dBTP mono.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from streaming_bot.domain.catalog_pipeline.raw_audio import RawAudio
from streaming_bot.domain.exceptions import DomainError


class AudioMasteringError(DomainError):
    """Error tipado para fallos en el masterizado."""


@dataclass(frozen=True, slots=True)
class MasteringProfile:
    """Perfil de masterizado dirigido a un DSP.

    Atributos:
        name: identificador legible del perfil (``spotify``, ``apple``...).
        integrated_lufs: target LUFS integrado segun EBU R128.
        true_peak_db: limite de true peak (dBTP), tipico -1.0.
        loudness_range_lu: target LRA (loudness range) tipico 11.
        sample_rate: frecuencia de muestreo del archivo final.
    """

    name: str
    integrated_lufs: float
    true_peak_db: float
    loudness_range_lu: float
    sample_rate: int

    @classmethod
    def spotify(cls) -> MasteringProfile:
        """Perfil estandar de streaming -14 LUFS."""
        return cls(
            name="spotify",
            integrated_lufs=-14.0,
            true_peak_db=-1.0,
            loudness_range_lu=11.0,
            sample_rate=44_100,
        )

    @classmethod
    def apple_music(cls) -> MasteringProfile:
        """Perfil Apple Music con Sound Check ON (-16 LUFS)."""
        return cls(
            name="apple_music",
            integrated_lufs=-16.0,
            true_peak_db=-1.0,
            loudness_range_lu=11.0,
            sample_rate=44_100,
        )

    @classmethod
    def podcast(cls) -> MasteringProfile:
        """Perfil para distribucion de podcasts (mono mix recomendado)."""
        return cls(
            name="podcast",
            integrated_lufs=-16.0,
            true_peak_db=-1.0,
            loudness_range_lu=8.0,
            sample_rate=48_000,
        )


@runtime_checkable
class IAudioMastering(Protocol):
    """Aplica un perfil de masterizado a un ``RawAudio``."""

    async def master(self, raw: RawAudio, profile: MasteringProfile) -> RawAudio:
        """Devuelve un ``RawAudio`` masterizado segun ``profile``.

        Raises:
            AudioMasteringError: fallo del backend (ffmpeg crash, formato
                no soportado, etc.).
        """
        ...
