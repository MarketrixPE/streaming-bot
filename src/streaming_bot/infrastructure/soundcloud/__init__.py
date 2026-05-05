"""Adaptadores SoundCloud: cliente sobre la API privada v2."""

from streaming_bot.infrastructure.soundcloud.soundcloud_v2_client import (
    SoundcloudClientError,
    SoundcloudV2Client,
)

__all__ = ["SoundcloudClientError", "SoundcloudV2Client"]
