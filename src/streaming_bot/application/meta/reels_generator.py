"""``ReelsGeneratorService``: pipeline auto que crea Reels con audio del catalogo.

Pasos:
1. Lookup en ``IStockFootageRepository`` por (niche, mood) -> ruta de clip 9:16.
2. Llama ``IReelBuilder.build`` (FFmpeg) con stock_video + audio_track + watermark.
3. Genera caption + hashtags via ``IReelCaptionGenerator`` (LLM).
4. Resuelve ``SmartLink`` ya creado por ``ISmartLinkProvider`` (smart link
   debe existir antes - lo crea el orchestrator de spillover una vez por track).
5. Devuelve ``GeneratedReel`` con todo listo para postear via instagrapi.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

from streaming_bot.domain.meta.reel import Reel
from streaming_bot.domain.meta.smart_link import SmartLink
from streaming_bot.domain.value_objects import Country

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from structlog.stdlib import BoundLogger


@runtime_checkable
class IStockFootageRepository(Protocol):
    """Lookup de stock footage por (niche, mood). v1 lookup local con metadata.json."""

    async def pick_clip(
        self,
        *,
        niche: str,
        mood: str | None = None,
    ) -> Path:
        """Devuelve la ruta a un clip vertical 9:16 random del pool. Lanza
        ``FileNotFoundError`` si el pool del nicho esta vacio.
        """
        ...


@runtime_checkable
class IReelBuilder(Protocol):
    """Combina stock_video + audio_track + caption overlay + watermark a un .mp4."""

    async def build(
        self,
        *,
        stock_video_path: Path,
        audio_track_path: Path,
        output_path: Path,
        artist_uri: str,
        max_seconds: int = 30,
    ) -> Path:
        """Devuelve la ruta del .mp4 generado. Vertical 1080x1920 ~30s."""
        ...


@runtime_checkable
class IReelCaptionGenerator(Protocol):
    """Genera caption corto (<200 chars) + hashtags por nicho."""

    async def generate(
        self,
        *,
        track_title: str,
        artist_name: str,
        niche: str,
        mood: str | None = None,
    ) -> tuple[str, tuple[str, ...]]:
        """Devuelve ``(caption, hashtags)``. Caption max 200 chars."""
        ...


@dataclass(frozen=True, slots=True)
class GeneratedReel:
    """Bundle resultado del pipeline. ``reel`` aun no esta posted."""

    reel: Reel
    stock_clip_path: Path
    audio_track_path: Path


class ReelsGeneratorService:
    """Pipeline orquestador: stock + audio -> reel listo para postear."""

    def __init__(
        self,
        *,
        stock_footage: IStockFootageRepository,
        reel_builder: IReelBuilder,
        caption_generator: IReelCaptionGenerator,
        output_dir: Path,
        logger: BoundLogger | None = None,
    ) -> None:
        self._stock = stock_footage
        self._builder = reel_builder
        self._captions = caption_generator
        self._output_dir = output_dir
        self._log: BoundLogger = logger or structlog.get_logger("meta.reels_generator")

    async def generate(
        self,
        *,
        account_id: str,
        track_uri: str,
        track_title: str,
        artist_name: str,
        artist_uri: str,
        audio_track_path: Path,
        niche: str,
        smart_link: SmartLink,
        smart_link_base_url: str,
        smart_link_country: object,
        mood: str | None = None,
    ) -> GeneratedReel:
        """Genera un Reel completo y lo devuelve listo para postear.

        ``smart_link_country`` se usa para resolver la URL publica desde el
        ``SmartLink``. Tipado como ``object`` aqui para no acoplar a Country
        en la firma; el caller pasa el ``Country`` correcto.
        """
        log = self._log.bind(
            account_id=account_id,
            track_uri=track_uri,
            niche=niche,
            mood=mood or "",
        )
        log.info("reels.start")

        if not isinstance(smart_link_country, Country):
            raise TypeError(
                f"smart_link_country debe ser Country, recibido {type(smart_link_country)}",
            )

        clip_path = await self._stock.pick_clip(niche=niche, mood=mood)
        log.debug("reels.stock_picked", clip=str(clip_path))

        output_path = self._output_dir / f"reel-{account_id}-{smart_link.short_id}.mp4"
        video_path = await self._builder.build(
            stock_video_path=clip_path,
            audio_track_path=audio_track_path,
            output_path=output_path,
            artist_uri=artist_uri,
        )
        log.debug("reels.video_built", video=str(video_path))

        caption, hashtags = await self._captions.generate(
            track_title=track_title,
            artist_name=artist_name,
            niche=niche,
            mood=mood,
        )
        caption = self._inject_smart_link(
            caption,
            smart_link.url_for(country=smart_link_country, base_url=smart_link_base_url),
        )

        reel = Reel.new(
            account_id=account_id,
            audio_track_uri=track_uri,
            video_path=video_path,
            caption=caption,
            hashtags=hashtags,
            smart_link=smart_link.url_for(
                country=smart_link_country,
                base_url=smart_link_base_url,
            ),
        )
        log.info("reels.done", reel_id=reel.id, hashtags_count=len(hashtags))
        return GeneratedReel(
            reel=reel,
            stock_clip_path=clip_path,
            audio_track_path=audio_track_path,
        )

    @staticmethod
    def _inject_smart_link(caption: str, link: str) -> str:
        """Mete el smart-link al final del caption respetando 200 chars."""
        suffix = f" {link}"
        max_caption = 200 - len(suffix)
        if max_caption <= 0:
            return link[:200]
        truncated = caption[:max_caption].rstrip()
        return f"{truncated}{suffix}"

    @staticmethod
    def _normalize_hashtags(raw: Sequence[str]) -> tuple[str, ...]:
        """Normaliza hashtags: minusculas, sin '#', sin espacios. Util para
        unificar la salida del caption generator (algunos LLMs devuelven
        "#tag", otros "tag").
        """
        cleaned: list[str] = []
        for item in raw:
            tag = item.strip().lstrip("#").lower()
            if tag:
                cleaned.append(tag)
        return tuple(cleaned)
