"""Tests del PostgresAccountRepository contra SQLite in-memory."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.entities import Account, AccountStatus
from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.repos.account_repository import (
    PostgresAccountRepository,
)


def _make_account(
    *,
    username: str = "user_pe",
    country: Country = Country.PE,
    status: AccountStatus | None = None,
    last_used_at: datetime | None = None,
) -> Account:
    return Account(
        id=f"id-{username}",
        username=username,
        password="ciphertext::dummy",
        country=country,
        status=status or AccountStatus.active(),
        last_used_at=last_used_at,
    )


async def test_add_then_get_round_trip(session: AsyncSession) -> None:
    repo = PostgresAccountRepository(session)
    original = _make_account(username="alice")

    await repo.add(original)
    fetched = await repo.get(original.id)

    assert fetched.id == original.id
    assert fetched.username == "alice"
    assert fetched.country == Country.PE
    assert fetched.status.is_usable


async def test_get_by_username_returns_none_when_missing(session: AsyncSession) -> None:
    repo = PostgresAccountRepository(session)

    result = await repo.get_by_username("ghost")

    assert result is None


async def test_update_persists_status_change(session: AsyncSession) -> None:
    repo = PostgresAccountRepository(session)
    account = _make_account(username="bob")
    await repo.add(account)

    account.deactivate("captcha-loop")
    await repo.update(account)

    refreshed = await repo.get(account.id)
    assert refreshed.status.state == "banned"
    assert refreshed.status.reason == "captcha-loop"


async def test_update_unknown_account_raises(session: AsyncSession) -> None:
    repo = PostgresAccountRepository(session)
    ghost = _make_account(username="ghost")

    with pytest.raises(DomainError):
        await repo.update(ghost)


async def test_list_active_orders_lru_first(session: AsyncSession) -> None:
    repo = PostgresAccountRepository(session)
    never_used = _make_account(username="never")
    recent = _make_account(
        username="recent",
        last_used_at=datetime(2026, 4, 27, tzinfo=UTC),
    )
    older = _make_account(
        username="older",
        last_used_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    banned = _make_account(
        username="banned",
        status=AccountStatus.banned("ban"),
    )
    for acc in (recent, banned, never_used, older):
        await repo.add(acc)

    actives = await repo.list_active()

    usernames = [a.username for a in actives]
    assert "banned" not in usernames
    # NULLS FIRST -> never; luego older (más antiguo); luego recent.
    assert usernames == ["never", "older", "recent"]
