"""``SunoGenerator``: ``IAIMusicGenerator`` sobre la API de Suno (studio-api).

Flujo:

1. ``POST {base}/api/generate/v2/`` con prompt + style + make_instrumental.
   Respuesta tipica: ``[{"id": "...", "audio_url": null, "status": "queued"}]``.
2. Polling a ``GET {base}/api/feed/?ids=<id>`` cada ``poll_interval``s hasta
   que ``audio_url`` aparezca o el ``status`` sea ``complete``/``streaming``.
3. Descarga el archivo de ``audio_url`` y lo persiste via
   ``IRawAudioStorage`` con nombre canonico ``{track_id}.mp3``.

Coste real Suno (Q4 2025): plan Pro ~$10/mes => 2500 creditos => 500 pistas
=> ~$0.02-0.05 por pista segun calidad.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from streaming_bot.domain.catalog_pipeline.raw_audio import (
    AudioFormat,
    IRawAudioStorage,
    RawAudio,
)
from streaming_bot.domain.ports.ai_music_generator import (
    AIMusicGenerationError,
    IAIMusicGenerator,
)

if TYPE_CHECKING:
    from streaming_bot.domain.catalog_pipeline.track_brief import TrackBrief


DEFAULT_BASE_URL = "https://studio-api.suno.ai"


class SunoGenerator(IAIMusicGenerator):
    """Adapter HTTP para Suno studio-api."""

    def __init__(
        self,
        *,
        api_key: str,
        storage: IRawAudioStorage,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_BASE_URL,
        poll_interval_seconds: float = 5.0,
        generation_timeout_seconds: float = 300.0,
        request_timeout_seconds: float = 60.0,
        default_sample_rate: int = 44_100,
    ) -> None:
        self._api_key = api_key
        self._storage = storage
        self._base_url = base_url.rstrip("/")
        self._poll_interval = poll_interval_seconds
        self._generation_timeout = generation_timeout_seconds
        self._request_timeout = request_timeout_seconds
        self._default_sample_rate = default_sample_rate
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=request_timeout_seconds)
        self._log = structlog.get_logger("suno_generator")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def generate(self, brief: TrackBrief, *, track_id: str) -> RawAudio:
        if not self._api_key:
            raise AIMusicGenerationError("suno: api_key vacia")

        clip_id = await self._submit(brief)
        audio_url, duration_ms = await self._poll(clip_id)
        data = await self._download(audio_url)
        path = await self._storage.save(
            data,
            track_id=track_id,
            audio_format=AudioFormat.MP3,
        )
        return RawAudio(
            bytes_path=path,
            format=AudioFormat.MP3,
            sample_rate=self._default_sample_rate,
            duration_ms=duration_ms or brief.duration_seconds * 1000,
        )

    async def _submit(self, brief: TrackBrief) -> str:
        url = f"{self._base_url}/api/generate/v2/"
        prompt = self._render_prompt(brief)
        payload = {
            "prompt": prompt,
            "tags": f"{brief.niche},{brief.mood}",
            "make_instrumental": brief.lyric_seed is None,
            "mv": "chirp-v3-5",
        }
        try:
            response = await self._http.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self._request_timeout,
            )
        except httpx.HTTPError as exc:
            raise AIMusicGenerationError(f"suno submit fallo: {exc}") from exc
        if response.status_code >= 400:
            raise AIMusicGenerationError(
                f"suno submit status={response.status_code} body={response.text[:200]}",
            )
        data: Any = response.json()
        clips = data if isinstance(data, list) else data.get("clips") or []
        if not clips:
            raise AIMusicGenerationError(f"suno submit sin clips: {data}")
        first = clips[0]
        clip_id = first.get("id") if isinstance(first, dict) else None
        if not isinstance(clip_id, str) or not clip_id:
            raise AIMusicGenerationError(f"suno submit sin clip_id: {first}")
        return clip_id

    async def _poll(self, clip_id: str) -> tuple[str, int]:
        url = f"{self._base_url}/api/feed/"
        deadline = asyncio.get_event_loop().time() + self._generation_timeout
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(self._poll_interval)
            try:
                response = await self._http.get(
                    url,
                    params={"ids": clip_id},
                    headers=self._headers(),
                    timeout=self._request_timeout,
                )
            except httpx.HTTPError as exc:
                self._log.warning("suno.poll_failed", clip_id=clip_id, error=str(exc))
                continue
            if response.status_code >= 400:
                self._log.warning(
                    "suno.poll_status_error",
                    clip_id=clip_id,
                    status=response.status_code,
                )
                continue
            data: Any = response.json()
            entries = data if isinstance(data, list) else data.get("clips") or []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if entry.get("id") != clip_id:
                    continue
                status = entry.get("status")
                audio_url = entry.get("audio_url")
                if status in {"complete", "streaming"} and audio_url:
                    duration_ms = int(float(entry.get("metadata", {}).get("duration", 0)) * 1000)
                    return audio_url, duration_ms
                if status == "error":
                    raise AIMusicGenerationError(
                        f"suno render error clip_id={clip_id} body={entry}",
                    )
        raise AIMusicGenerationError(
            f"suno timeout esperando render clip_id={clip_id} "
            f"tras {self._generation_timeout}s",
        )

    async def _download(self, audio_url: str) -> bytes:
        try:
            response = await self._http.get(audio_url, timeout=self._request_timeout)
        except httpx.HTTPError as exc:
            raise AIMusicGenerationError(f"suno download fallo: {exc}") from exc
        if response.status_code >= 400:
            raise AIMusicGenerationError(
                f"suno download status={response.status_code}",
            )
        return response.content

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _render_prompt(brief: TrackBrief) -> str:
        """Convierte el brief a un prompt textual rico para Suno."""
        low, high = brief.bpm_range
        parts = [
            f"{brief.niche} track",
            f"mood: {brief.mood}",
            f"bpm: {low}-{high}",
            f"length: {brief.duration_seconds}s",
        ]
        if brief.lyric_seed:
            parts.append(f"lyrics seed: {brief.lyric_seed}")
        return ", ".join(parts)
