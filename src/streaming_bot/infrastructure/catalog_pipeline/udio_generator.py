"""``UdioGenerator``: ``IAIMusicGenerator`` sobre la API de Udio.

Misma filosofia que ``SunoGenerator`` (submit -> poll -> download), pero
contra el endpoint publico de Udio. Se usa como fallback cuando Suno
devuelve error o saturacion. El contrato externo es identico.

Coste real Udio (Q4 2025): ~$0.04-0.06 por pista en plan Standard.
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


DEFAULT_BASE_URL = "https://api.udio.com"


class UdioGenerator(IAIMusicGenerator):
    """Adapter HTTP para Udio."""

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
        self._log = structlog.get_logger("udio_generator")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def generate(self, brief: TrackBrief, *, track_id: str) -> RawAudio:
        if not self._api_key:
            raise AIMusicGenerationError("udio: api_key vacia")

        job_id = await self._submit(brief)
        audio_url, duration_ms = await self._poll(job_id)
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
        url = f"{self._base_url}/v1/generations"
        low, high = brief.bpm_range
        payload = {
            "prompt": brief.mood,
            "tags": [brief.niche, brief.mood],
            "bpm_min": low,
            "bpm_max": high,
            "duration": brief.duration_seconds,
            "instrumental": brief.lyric_seed is None,
        }
        if brief.lyric_seed:
            payload["lyrics_seed"] = brief.lyric_seed
        try:
            response = await self._http.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self._request_timeout,
            )
        except httpx.HTTPError as exc:
            raise AIMusicGenerationError(f"udio submit fallo: {exc}") from exc
        if response.status_code >= 400:
            raise AIMusicGenerationError(
                f"udio submit status={response.status_code} body={response.text[:200]}",
            )
        data: Any = response.json()
        job_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(job_id, str) or not job_id:
            raise AIMusicGenerationError(f"udio submit sin id: {data}")
        return job_id

    async def _poll(self, job_id: str) -> tuple[str, int]:
        url = f"{self._base_url}/v1/generations/{job_id}"
        deadline = asyncio.get_event_loop().time() + self._generation_timeout
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(self._poll_interval)
            try:
                response = await self._http.get(
                    url,
                    headers=self._headers(),
                    timeout=self._request_timeout,
                )
            except httpx.HTTPError as exc:
                self._log.warning("udio.poll_failed", job_id=job_id, error=str(exc))
                continue
            if response.status_code >= 400:
                self._log.warning(
                    "udio.poll_status_error",
                    job_id=job_id,
                    status=response.status_code,
                )
                continue
            data: Any = response.json()
            if not isinstance(data, dict):
                continue
            status = data.get("status")
            audio_url = data.get("audio_url")
            if status == "complete" and audio_url:
                duration_ms = int(float(data.get("duration_seconds", 0)) * 1000)
                return audio_url, duration_ms
            if status == "failed":
                raise AIMusicGenerationError(
                    f"udio render fallo job_id={job_id} body={data}",
                )
        raise AIMusicGenerationError(
            f"udio timeout esperando render job_id={job_id} "
            f"tras {self._generation_timeout}s",
        )

    async def _download(self, audio_url: str) -> bytes:
        try:
            response = await self._http.get(audio_url, timeout=self._request_timeout)
        except httpx.HTTPError as exc:
            raise AIMusicGenerationError(f"udio download fallo: {exc}") from exc
        if response.status_code >= 400:
            raise AIMusicGenerationError(f"udio download status={response.status_code}")
        return response.content

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
