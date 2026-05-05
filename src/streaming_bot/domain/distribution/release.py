"""Agregado Release y value objects de submission.

Un `Release` representa el envio de un conjunto de tracks (single, EP o
album) a UN distribuidor concreto. La estrategia multi-distribuidor genera
N releases distintas (una por distro) a partir del mismo Track de catalogo,
cada una con un `artist_name` distinto (alias) para no colocar todos los
huevos en una sola cesta legal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from uuid import uuid4

from streaming_bot.domain.distribution.distributor_id import DistributorId


class ReleaseStatus(str, Enum):
    """Estado del release a lo largo del ciclo de vida en el distribuidor."""

    DRAFT = "draft"  # construido pero no enviado
    SUBMITTED = "submitted"  # entregado al distribuidor (sin confirmacion final)
    IN_REVIEW = "in_review"  # en revision manual / antifraude del distro
    LIVE = "live"  # publicado en stores
    REJECTED = "rejected"  # rechazado (metadata, derechos, etc.)
    TAKEN_DOWN = "taken_down"  # bajado tras takedown / strike


@dataclass(frozen=True, slots=True)
class ArtistAlias:
    """Alias de artista usado en un distribuidor concreto.

    Modela la relacion (track del catalogo) -> (nombre publicado en distro).
    Persistimos el mapping para asegurar que el mismo track use SIEMPRE el
    mismo alias en el mismo distribuidor (los stores ya indexaron ese
    artista; cambiarlo crea splits y duplicados).
    """

    track_id: str
    distributor: DistributorId
    alias_name: str
    label_name: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class TrackRef:
    """Referencia inmutable a un track del catalogo, lista para upload.

    El distribuidor NO necesita conocer toda la `Song`: solo el archivo de
    audio, el titulo, el ISRC opcional y la duracion. El `artist_name` aqui
    es el ALIAS asignado por el alias_resolver, NO el nombre real del
    catalogo.
    """

    track_id: str
    title: str
    artist_name: str
    audio_path: Path
    isrc: str | None = None
    duration_seconds: int | None = None
    explicit: bool = False


@dataclass(frozen=True, slots=True)
class Release:
    """Agregado de release dirigido a UN distribuidor.

    Para singles, `tracks` contiene un unico `TrackRef`. Para EPs/albums,
    multiples. La `artist_name` y `label_name` se aplican al release entero
    (todos los tracks comparten el mismo alias en este distro).
    """

    release_id: str
    tracks: tuple[TrackRef, ...]
    artist_name: str
    label_name: str
    distributor: DistributorId
    release_date: date
    isrc: str | None = None
    upc: str | None = None
    status: ReleaseStatus = ReleaseStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.tracks:
            raise ValueError("Release debe tener al menos un track")
        if not self.artist_name:
            raise ValueError("artist_name no puede estar vacio")
        if not self.label_name:
            raise ValueError("label_name no puede estar vacio")

    @classmethod
    def new(
        cls,
        *,
        tracks: tuple[TrackRef, ...],
        artist_name: str,
        label_name: str,
        distributor: DistributorId,
        release_date: date,
        isrc: str | None = None,
        upc: str | None = None,
    ) -> Release:
        return cls(
            release_id=str(uuid4()),
            tracks=tracks,
            artist_name=artist_name,
            label_name=label_name,
            distributor=distributor,
            release_date=release_date,
            isrc=isrc,
            upc=upc,
        )


@dataclass(frozen=True, slots=True)
class ReleaseSubmission:
    """Resultado de submit_release: confirmacion del distribuidor.

    `submission_id` es el identificador interno asignado por el distribuidor
    (necesario despues para `get_status` o `request_takedown`).
    """

    submission_id: str
    distributor: DistributorId
    release_id: str
    submitted_at: datetime
    status: ReleaseStatus = ReleaseStatus.SUBMITTED
    raw_response: str | None = None
