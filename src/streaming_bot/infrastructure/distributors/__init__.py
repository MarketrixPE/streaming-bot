"""Adapters HTTP / scraping de distribuidores y router paralelo.

- `DistroKidAdapter`: scrape browser-based via Patchright (DistroKid no
  expone API publica oficial Q1 2026).
- `RouteNoteAdapter`: HTTP REST autenticado por cookies de session.
- `DispatcherRouter`: orquesta envios paralelos a varios adapters.
"""

from streaming_bot.infrastructure.distributors.dispatcher_router import (
    DispatcherRouter,
)
from streaming_bot.infrastructure.distributors.distrokid_adapter import (
    DistroKidAdapter,
    DistroKidCredentials,
    DistroKidSelectors,
)
from streaming_bot.infrastructure.distributors.routenote_adapter import (
    RouteNoteAdapter,
    RouteNoteCredentials,
)

__all__ = [
    "DispatcherRouter",
    "DistroKidAdapter",
    "DistroKidCredentials",
    "DistroKidSelectors",
    "RouteNoteAdapter",
    "RouteNoteCredentials",
]
