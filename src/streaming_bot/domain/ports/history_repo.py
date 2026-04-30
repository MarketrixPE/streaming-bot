"""Repositorio para historial de streams y sesiones (auditoria + analytics)."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from streaming_bot.domain.history import SessionRecord, StreamHistory


@runtime_checkable
class IStreamHistoryRepository(Protocol):
    async def add(self, history: StreamHistory) -> None: ...
    async def list_for_song(
        self,
        song_id: str,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[StreamHistory]: ...
    async def count_for_song_today(self, song_id: str) -> int: ...
    async def count_for_account_today(self, account_id: str) -> int: ...


@runtime_checkable
class ISessionRecordRepository(Protocol):
    async def add(self, record: SessionRecord) -> None: ...
    async def get(self, session_id: str) -> SessionRecord | None: ...
    async def list_for_account(
        self,
        account_id: str,
        *,
        limit: int = 50,
    ) -> list[SessionRecord]: ...
