"""Puerto para generar audio con servicios de musica IA (Suno, Udio, etc.)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from streaming_bot.domain.catalog_pipeline.raw_audio import RawAudio
from streaming_bot.domain.catalog_pipeline.track_brief import TrackBrief
from streaming_bot.domain.exceptions import DomainError


class AIMusicGenerationError(DomainError):
    """Error tipado para fallos del puerto de generacion musical."""


@runtime_checkable
class IAIMusicGenerator(Protocol):
    """Genera una pista a partir de un encargo creativo.

    Implementaciones tipicas: ``SunoGenerator``, ``UdioGenerator``. La
    semantica acordada es:

    - El generador ENVIA el job al proveedor.
    - Hace polling hasta que el render esta listo.
    - Descarga los bytes y los persiste via ``IRawAudioStorage``.
    - Devuelve un ``RawAudio`` con la ruta canonica del archivo.
    """

    async def generate(self, brief: TrackBrief, *, track_id: str) -> RawAudio:
        """Produce una pista para el ``brief`` dado.

        Args:
            brief: encargo creativo.
            track_id: identificador estable usado para nombrar el archivo
                en el storage (idempotencia + traza).

        Raises:
            AIMusicGenerationError: cualquier fallo no recuperable.
        """
        ...
