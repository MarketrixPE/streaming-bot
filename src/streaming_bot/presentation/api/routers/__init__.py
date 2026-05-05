"""Routers FastAPI v1 (read-only)."""

from streaming_bot.presentation.api.routers import (
    accounts,
    catalog,
    health,
    jobs,
    metrics,
    routing,
)

__all__ = [
    "accounts",
    "catalog",
    "health",
    "jobs",
    "metrics",
    "routing",
]
