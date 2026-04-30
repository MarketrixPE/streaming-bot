"""Proveedores de proxies."""

from streaming_bot.infrastructure.proxies.proxy_pool import (
    NoProxyProvider,
    StaticFileProxyProvider,
)

__all__ = ["NoProxyProvider", "StaticFileProxyProvider"]
