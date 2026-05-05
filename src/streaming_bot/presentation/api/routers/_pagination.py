"""Helpers de paginacion cursor-based compartidos entre routers."""

from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
from typing import TypeVar

from streaming_bot.presentation.api.schemas import PaginatedResponse

_TItem = TypeVar("_TItem")
_TDto = TypeVar("_TDto")

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def decode_cursor(cursor: str | None) -> int:
    """Decodifica cursor opaco -> offset entero. 0 si invalido."""
    if not cursor:
        return 0
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")
        offset = int(decoded)
        return max(offset, 0)
    except (ValueError, UnicodeDecodeError):
        return 0


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


def paginate(
    items: Sequence[_TItem],
    *,
    limit: int,
    cursor: str | None,
    map_item: Callable[[_TItem], _TDto],
) -> PaginatedResponse[_TDto]:
    """Pagina una lista materializada y mapea cada item a su DTO.

    Cursor-based simple: el cursor codifica un offset entero. Se devuelve
    ``next_cursor=None`` cuando ya no quedan items adelante.
    """
    offset = decode_cursor(cursor)
    page = list(items[offset : offset + limit])
    next_offset = offset + len(page)
    next_cursor = encode_cursor(next_offset) if next_offset < len(items) else None
    return PaginatedResponse[_TDto](
        items=[map_item(item) for item in page],
        limit=limit,
        next_cursor=next_cursor,
        total=len(items),
    )
