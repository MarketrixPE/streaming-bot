"""``OpenAIMetadataGenerator``: ``IMetadataGenerator`` via OpenAI Chat Completions.

Pide al LLM que devuelva un JSON estructurado con titulo, alias de artista,
genero, subgenero, tags y descripcion SEO. Usamos ``response_format=json_object``
para forzar un payload parseable y nos protegemos contra desviaciones leves
con validacion explicita.

Coste real (Q4 2025) gpt-4o-mini ~ $0.15/1M input tokens + $0.60/1M output:
- Input ~500 tokens, output ~250 tokens => ~$0.0002 + $0.00015 = $0.00035.
- Margen para gpt-4o full: ~$0.005 por pista.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from streaming_bot.domain.catalog_pipeline.metadata_pack import MetadataPack
from streaming_bot.domain.ports.metadata_generator import (
    IMetadataGenerator,
    MetadataGenerationError,
)

if TYPE_CHECKING:
    from streaming_bot.domain.catalog_pipeline.raw_audio import RawAudio
    from streaming_bot.domain.catalog_pipeline.track_brief import TrackBrief


DEFAULT_BASE_URL = "https://api.openai.com"
DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIMetadataGenerator(IMetadataGenerator):
    """Adapter HTTP a OpenAI Chat Completions con salida JSON estricta."""

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        request_timeout_seconds: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._request_timeout = request_timeout_seconds
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=request_timeout_seconds)
        self._log = structlog.get_logger("openai_metadata_generator")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def enrich(
        self,
        brief: TrackBrief,
        raw: RawAudio,
        *,
        cover_art_path: Path,
    ) -> MetadataPack:
        if not self._api_key:
            raise MetadataGenerationError("openai: api_key vacia")

        payload = self._build_payload(brief, raw)
        try:
            response = await self._http.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self._request_timeout,
            )
        except httpx.HTTPError as exc:
            raise MetadataGenerationError(f"openai request fallo: {exc}") from exc
        if response.status_code >= 400:
            raise MetadataGenerationError(
                f"openai status={response.status_code} body={response.text[:200]}",
            )
        data: Any = response.json()
        return self._parse(data, cover_art_path=cover_art_path)

    def _build_payload(self, brief: TrackBrief, raw: RawAudio) -> dict[str, Any]:
        system = (
            "Eres un editor SEO especializado en streaming de musica de fondo."
            " Devuelves SIEMPRE un JSON estricto con las claves:"
            " title (str), artist_alias (str), genre (str), subgenre (str),"
            " tags (lista de strings), description (str con 1-2 frases SEO)."
            " Nada de markdown ni texto extra fuera del JSON."
        )
        low, high = brief.bpm_range
        user = (
            f"Genera metadata para una pista del nicho '{brief.niche}',"
            f" mood '{brief.mood}', BPM {low}-{high},"
            f" duracion {raw.duration_seconds()}s. Geo objetivo principal:"
            f" {brief.primary_geo().value}. {self._lyrics_hint(brief)}"
            " El alias del artista debe sonar natural, no generico."
        )
        return {
            "model": self._model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.7,
        }

    @staticmethod
    def _lyrics_hint(brief: TrackBrief) -> str:
        if brief.lyric_seed:
            return f"Letra con seed: '{brief.lyric_seed}'."
        return "La pista es instrumental."

    def _parse(self, data: Any, *, cover_art_path: Path) -> MetadataPack:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise MetadataGenerationError(
                f"openai response sin choices/content: {data}",
            ) from exc
        try:
            parsed: Any = json.loads(content)
        except json.JSONDecodeError as exc:
            raise MetadataGenerationError(
                f"openai content no es JSON valido: {content[:200]}",
            ) from exc
        if not isinstance(parsed, dict):
            raise MetadataGenerationError(f"openai JSON no es objeto: {parsed}")

        try:
            tags_raw = parsed["tags"]
            if not isinstance(tags_raw, list):
                raise TypeError("tags no es lista")
            tags = tuple(str(tag) for tag in tags_raw if str(tag).strip())
            return MetadataPack(
                title=str(parsed["title"]).strip(),
                artist_alias=str(parsed["artist_alias"]).strip(),
                genre=str(parsed["genre"]).strip(),
                subgenre=str(parsed["subgenre"]).strip(),
                tags=tags,
                description=str(parsed["description"]).strip(),
                cover_art_path=cover_art_path,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MetadataGenerationError(
                f"openai JSON con campos invalidos: {parsed}",
            ) from exc

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
