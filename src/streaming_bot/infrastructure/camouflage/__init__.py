"""Implementaciones del puerto ICamouflagePool."""

from streaming_bot.infrastructure.camouflage.in_memory_camouflage_pool import (
    InMemoryCamouflagePool,
)
from streaming_bot.infrastructure.camouflage.postgres_camouflage_pool import (
    PostgresCamouflagePool,
)

__all__ = [
    "InMemoryCamouflagePool",
    "PostgresCamouflagePool",
]
