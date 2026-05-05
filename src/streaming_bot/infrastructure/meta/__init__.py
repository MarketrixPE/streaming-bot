"""Adapters Meta (Instagram + ffmpeg + smart-link + stock footage)."""

from streaming_bot.infrastructure.meta.ffmpeg_reel_builder import FfmpegReelBuilder
from streaming_bot.infrastructure.meta.instagrapi_adapter import InstagrapiAdapter
from streaming_bot.infrastructure.meta.linkfire_smart_link_adapter import (
    LinkfireSmartLinkAdapter,
    SelfHostedSmartLinkAdapter,
)
from streaming_bot.infrastructure.meta.patchright_instagram_fallback import (
    PatchrightInstagramFallback,
)
from streaming_bot.infrastructure.meta.stock_footage_repository import (
    LocalStockFootageRepository,
)

__all__ = [
    "FfmpegReelBuilder",
    "InstagrapiAdapter",
    "LinkfireSmartLinkAdapter",
    "LocalStockFootageRepository",
    "PatchrightInstagramFallback",
    "SelfHostedSmartLinkAdapter",
]
