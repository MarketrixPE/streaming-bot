"""Router /v1 routing: tier asignado por el ``MultiTierGeoRouter``.

El endpoint resuelve un track por id, intenta obtener su TrackHealthScore
desde el ``ITrackHealthRepository`` (si esta cableado en el container)
y delega al router de tiers para devolver la asignacion.

En modo dev (sin track health), el endpoint devuelve un tier conservador
basado solo en el rol/baseline del track.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path

from streaming_bot.application.routing.tier_router import MultiTierGeoRouter
from streaming_bot.domain.ports import ISongRepository
from streaming_bot.domain.routing.tier import Tier
from streaming_bot.domain.routing.track_health import TrackHealthScore
from streaming_bot.domain.song import Song
from streaming_bot.presentation.api.dependencies import (
    get_container,
    get_song_repository,
    require_role,
)
from streaming_bot.presentation.api.errors import NotFoundError
from streaming_bot.presentation.api.schemas import TierAssignmentDTO

router = APIRouter(
    prefix="/v1/routing",
    tags=["routing"],
    dependencies=[Depends(require_role("viewer", "operator", "admin"))],
)


def _resolve_track_health_repo(container: Any) -> Any | None:
    """Recupera el repo de track health si el container lo expone."""
    return getattr(container, "track_health_repository", None)


def _fallback_score(song: Song) -> TrackHealthScore:
    """Score conservador cuando no hay datos historicos de track health.

    Usamos baseline_streams_per_day para estimar plays_30d y dejamos
    save/skip rates en valores neutros. age_days=999 fuerza el fallback
    a la rama "track maduro" del router.
    """
    plays_30d = max(int(song.baseline_streams_per_day * 30), 0)
    return TrackHealthScore(
        age_days=365,
        plays_30d=plays_30d,
        save_rate=0.03,
        skip_rate=0.40,
        saturation_score=0.0,
        computed_at=datetime.now(UTC),
    )


@router.get(
    "/tier_for_track/{track_id}",
    response_model=TierAssignmentDTO,
    summary="Tier asignado para un track",
    description=(
        "Resuelve el tier (TIER_1/2/3) que el MultiTierGeoRouter "
        "asignaria al track segun su salud actual. Si no hay snapshot "
        "de track_health disponible, se usa un score conservador "
        "derivado del baseline diario y se anota rationale.fallback=true."
    ),
)
async def tier_for_track(
    track_id: Annotated[str, Path(description="ULID interno del track")],
    songs_repo: Annotated[ISongRepository, Depends(get_song_repository)],
    container: Annotated[Any, Depends(get_container)],
) -> TierAssignmentDTO:
    song = await songs_repo.get(track_id)
    if song is None:
        raise NotFoundError("track", track_id)

    health_repo = _resolve_track_health_repo(container)
    fallback = False
    score: TrackHealthScore
    if health_repo is None:
        score = _fallback_score(song)
        fallback = True
    else:
        loaded = await health_repo.get_latest(song.spotify_uri)
        if loaded is None:
            score = _fallback_score(song)
            fallback = True
        else:
            score = loaded

    router_service = MultiTierGeoRouter()
    tier: Tier = router_service.pick_tier(track=song, score=score)
    return TierAssignmentDTO(
        track_id=track_id,
        spotify_uri=song.spotify_uri,
        tier=tier.value,
        rationale={
            "fallback": fallback,
            "age_days": score.age_days,
            "plays_30d": score.plays_30d,
            "save_rate": score.save_rate,
            "skip_rate": score.skip_rate,
            "saturation_score": score.saturation_score,
        },
    )
