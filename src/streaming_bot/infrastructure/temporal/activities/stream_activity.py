"""Activity execute_stream_job: ejecuta un ScheduledJob via use case.

Glue minimal entre Temporal y el StreamSongUseCase. La activity:
1. Resuelve el container global (registrado por temporal_worker.py).
2. Construye StreamSongRequest desde los args primitivos.
3. Llama use_case.execute(...).
4. Devuelve un dict serializable con outcome para que el workflow lo logue.

Si el use case lanza TransientError, Temporal lo reintenta segun la
RetryPolicy declarada en el workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from temporalio import activity

if TYPE_CHECKING:
    from streaming_bot.domain.value_objects import Country


@dataclass(slots=True)
class ExecuteStreamArgs:
    """Argumentos serializables para la activity."""

    job_id: str
    account_id: str
    song_id: str
    country: str


# Container global registrado por el worker. Lo dejamos como Any para no
# imponer un tipo concreto al worker (puede ser ProductionContainer o un
# stub de tests).
_container: Any = None


def register_container(container: Any) -> None:
    """Registra el container global usado por las activities."""
    global _container  # noqa: PLW0603
    _container = container


@activity.defn(name="execute_stream_job")
async def execute_stream_job(args: ExecuteStreamArgs) -> dict[str, Any]:
    """Ejecuta un job de stream usando el container productivo."""
    log = structlog.get_logger("activity.execute_stream_job").bind(
        job_id=args.job_id,
        account_id=args.account_id,
    )
    if _container is None:
        log.error("container_not_registered")
        return {
            "job_id": args.job_id,
            "success": False,
            "error": "container_not_registered",
        }

    # IMPORT diferido: evita acoplar el modulo de activities a domain en
    # tiempo de carga (Temporal sandbox-friendly).
    from streaming_bot.application.stream_song import StreamSongRequest
    from streaming_bot.domain.value_objects import Country

    target_url = await _resolve_target_url(args.song_id, country=Country(args.country))
    request = StreamSongRequest(account_id=args.account_id, target_url=target_url)

    use_case = _container.make_stream_song_use_case()
    try:
        result = await use_case.execute(request)
    except Exception as exc:
        log.exception("stream_activity.failed", error=str(exc))
        # Re-lanzamos para que Temporal aplique el retry policy.
        raise

    return {
        "job_id": args.job_id,
        "success": result.success,
        "duration_ms": result.duration_ms,
        "error": result.error_message or "",
    }


async def _resolve_target_url(song_id: str, *, country: Country) -> str:  # noqa: ARG001
    """Construye target_url de un track. Por ahora simple: spotify URI -> URL.

    A futuro: routing por DSP segun song.dsp_uris (Spotify/SoundCloud/Deezer).
    """
    if song_id.startswith("spotify:track:"):
        track_id = song_id.rpartition(":")[2]
        return f"https://open.spotify.com/track/{track_id}"
    return song_id
