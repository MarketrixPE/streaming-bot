"""Router /v1 catalogo: tracks, artistas y labels.

Todas las rutas requieren rol viewer/operator/admin (lectura).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from streaming_bot.domain.artist import Artist
from streaming_bot.domain.label import Label
from streaming_bot.domain.ports import (
    IArtistRepository,
    ILabelRepository,
    ISongRepository,
)
from streaming_bot.domain.song import Song, SongRole
from streaming_bot.domain.value_objects import Country
from streaming_bot.presentation.api.dependencies import (
    get_artist_repository,
    get_label_repository,
    get_song_repository,
    require_role,
)
from streaming_bot.presentation.api.errors import NotFoundError
from streaming_bot.presentation.api.routers._pagination import MAX_LIMIT, paginate
from streaming_bot.presentation.api.schemas import (
    ArtistDTO,
    LabelDTO,
    PaginatedResponse,
    TrackDTO,
)

router = APIRouter(
    prefix="/v1",
    tags=["catalog"],
    dependencies=[Depends(require_role("viewer", "operator", "admin"))],
)


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------
def _track_to_dto(song: Song) -> TrackDTO:
    return TrackDTO(
        spotify_uri=song.spotify_uri,
        title=song.title,
        artist_name=song.artist_name,
        artist_uri=song.artist_uri,
        role=song.role.value,
        duration_seconds=song.metadata.duration_seconds,
        isrc=song.metadata.isrc,
        label=song.metadata.label,
        distributor=song.distributor.value if song.distributor else None,
        tier=song.tier.value,
        is_active=song.is_active,
        baseline_streams_per_day=song.baseline_streams_per_day,
        target_streams_per_day=song.target_streams_per_day,
        current_streams_today=song.current_streams_today,
        spike_oct2025_flag=song.spike_oct2025_flag,
        primary_artist_id=song.primary_artist_id,
        label_id=song.label_id,
    )


@router.get(
    "/tracks",
    response_model=PaginatedResponse[TrackDTO],
    summary="Lista de tracks paginada",
    description=(
        "Devuelve los tracks del catalogo. Soporta filtros por rol "
        "(target/camouflage/discovery) y por mercado primario via query "
        "string. Paginacion cursor-based: el cliente reenvia next_cursor."
    ),
)
async def list_tracks(
    songs_repo: Annotated[ISongRepository, Depends(get_song_repository)],
    role: Annotated[
        str | None,
        Query(description="Filtra por rol (target|camouflage|discovery)."),
    ] = None,
    market: Annotated[
        str | None,
        Query(description="Mercado primario ISO-3166 alpha-2 (PE, MX, US...)."),
    ] = None,
    cursor: Annotated[str | None, Query(description="Cursor opaco")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
) -> PaginatedResponse[TrackDTO]:
    songs: list[Song]
    if market is not None:
        try:
            country = Country(market.upper())
        except ValueError as exc:
            raise NotFoundError("market", market) from exc
        songs = await songs_repo.list_targets_by_market(country)
    elif role is not None:
        try:
            song_role = SongRole(role.lower())
        except ValueError as exc:
            raise NotFoundError("role", role) from exc
        songs = await songs_repo.list_by_role(song_role)
    else:
        songs = await songs_repo.list_by_role(SongRole.TARGET)
    return paginate(songs, limit=limit, cursor=cursor, map_item=_track_to_dto)


@router.get(
    "/tracks/{track_id}",
    response_model=TrackDTO,
    summary="Detalle de un track",
    description=(
        "Resuelve un track por su id interno (ULID). Devuelve 404 si "
        "el id no existe en el catalogo."
    ),
)
async def get_track(
    track_id: Annotated[str, Path(description="ID interno (ULID) del track")],
    songs_repo: Annotated[ISongRepository, Depends(get_song_repository)],
) -> TrackDTO:
    song = await songs_repo.get(track_id)
    if song is None:
        raise NotFoundError("track", track_id)
    return _track_to_dto(song)


# ---------------------------------------------------------------------------
# Artistas
# ---------------------------------------------------------------------------
def _artist_to_dto(artist: Artist) -> ArtistDTO:
    return ArtistDTO(
        id=artist.id,
        name=artist.name,
        spotify_uri=artist.spotify_uri,
        primary_country=artist.primary_country.value if artist.primary_country else None,
        label_id=artist.label_id,
        status=artist.status.value,
        has_spike_history=artist.has_spike_history,
        notes=artist.notes,
        created_at=artist.created_at,
        updated_at=artist.updated_at,
    )


@router.get(
    "/artists",
    response_model=PaginatedResponse[ArtistDTO],
    summary="Lista de artistas",
    description="Devuelve todos los artistas registrados con paginacion cursor-based.",
)
async def list_artists(
    artists_repo: Annotated[IArtistRepository, Depends(get_artist_repository)],
    cursor: Annotated[str | None, Query(description="Cursor opaco")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
) -> PaginatedResponse[ArtistDTO]:
    artists = await artists_repo.list_all()
    return paginate(artists, limit=limit, cursor=cursor, map_item=_artist_to_dto)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
def _label_to_dto(label: Label) -> LabelDTO:
    return LabelDTO(
        id=label.id,
        name=label.name,
        distributor=label.distributor.value,
        distributor_account_id=label.distributor_account_id,
        owner_email=label.owner_email,
        health=label.health.value,
        last_health_check=label.last_health_check,
        notes=label.notes,
        created_at=label.created_at,
        updated_at=label.updated_at,
    )


@router.get(
    "/labels",
    response_model=PaginatedResponse[LabelDTO],
    summary="Lista de sellos / distribuidores",
    description="Devuelve todos los labels registrados. Paginacion cursor-based.",
)
async def list_labels(
    labels_repo: Annotated[ILabelRepository, Depends(get_label_repository)],
    cursor: Annotated[str | None, Query(description="Cursor opaco")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
) -> PaginatedResponse[LabelDTO]:
    labels = await labels_repo.list_all()
    return paginate(labels, limit=limit, cursor=cursor, map_item=_label_to_dto)
