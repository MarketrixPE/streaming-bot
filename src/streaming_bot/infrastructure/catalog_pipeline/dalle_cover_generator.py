"""``DalleCoverGenerator``: ``ICoverArtGenerator`` sobre la API de OpenAI Images.

Pide un PNG cuadrado al endpoint ``/v1/images/generations`` con
``model=dall-e-3`` y ``size=1024x1024`` (el limite mas grande de DALL-E 3).
La portada final 3000x3000 se obtiene aguas abajo via upscaling externo
(no hace falta para metadatos de las tiendas, que aceptan minimo 3000x3000
pero el upscaling es trivial). Para mantener este adapter sin nuevas
dependencias, devolvemos la imagen tal y como la entrega DALL-E.

Coste DALL-E 3 (Q4 2025): ~ $0.04 por imagen 1024x1024 hd.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import httpx
import structlog

from streaming_bot.domain.ports.cover_art_generator import (
    CoverArtGenerationError,
    ICoverArtGenerator,
)

if TYPE_CHECKING:
    from streaming_bot.domain.catalog_pipeline.track_brief import TrackBrief


DEFAULT_BASE_URL = "https://api.openai.com"
DEFAULT_MODEL = "dall-e-3"


class DalleCoverGenerator(ICoverArtGenerator):
    """Adapter ``ICoverArtGenerator`` sobre OpenAI Images."""

    def __init__(
        self,
        *,
        api_key: str,
        output_dir: Path,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        size: str = "1024x1024",
        quality: str = "hd",
        request_timeout_seconds: float = 90.0,
    ) -> None:
        self._api_key = api_key
        self._output_dir = output_dir
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._size = size
        self._quality = quality
        self._request_timeout = request_timeout_seconds
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=request_timeout_seconds)
        self._log = structlog.get_logger("dalle_cover_generator")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def generate(self, brief: TrackBrief, *, track_id: str) -> Path:
        if not self._api_key:
            raise CoverArtGenerationError("dalle: api_key vacia")

        payload = {
            "model": self._model,
            "prompt": self._render_prompt(brief),
            "size": self._size,
            "quality": self._quality,
            "n": 1,
            "response_format": "b64_json",
        }
        try:
            response = await self._http.post(
                f"{self._base_url}/v1/images/generations",
                json=payload,
                headers=self._headers(),
                timeout=self._request_timeout,
            )
        except httpx.HTTPError as exc:
            raise CoverArtGenerationError(f"dalle request fallo: {exc}") from exc
        if response.status_code >= 400:
            raise CoverArtGenerationError(
                f"dalle status={response.status_code} body={response.text[:200]}",
            )
        data: Any = response.json()
        b64_payload = self._extract_b64(data)
        png_bytes = base64.b64decode(b64_payload)

        output_path = self._output_dir / f"{track_id}.cover.png"
        await anyio.Path(self._output_dir).mkdir(parents=True, exist_ok=True)
        await anyio.Path(output_path).write_bytes(png_bytes)
        self._log.info(
            "dalle.cover.saved",
            track_id=track_id,
            path=str(output_path),
            size_bytes=len(png_bytes),
        )
        return output_path

    @staticmethod
    def _extract_b64(data: Any) -> str:
        try:
            entry = data["data"][0]
            value = entry["b64_json"]
        except (KeyError, IndexError, TypeError) as exc:
            raise CoverArtGenerationError(
                f"dalle response sin b64_json: {data}",
            ) from exc
        if not isinstance(value, str) or not value:
            raise CoverArtGenerationError(f"dalle b64_json vacio: {entry}")
        return value

    @staticmethod
    def _render_prompt(brief: TrackBrief) -> str:
        """Prompt conciso para DALL-E describiendo portada por nicho."""
        return (
            f"Album cover artwork for a {brief.niche} track,"
            f" mood: {brief.mood}, atmospheric, high contrast,"
            f" no text, no logos, square composition, photorealistic textures."
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
