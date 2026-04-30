"""Tests del PostgresModemRepository."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.modem import Modem, ModemHardware, ModemState
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.repos.modem_repository import (
    PostgresModemRepository,
)


def _make_modem(
    *,
    imei: str,
    iccid: str,
    country: Country = Country.PE,
    state: ModemState = ModemState.READY,
    last_used_at: datetime | None = None,
) -> Modem:
    hw = ModemHardware(
        imei=imei,
        iccid=iccid,
        model="Quectel EG25-G",
        serial_port=f"/dev/ttyUSB-{imei[-2:]}",
        operator="Movistar PE",
        sim_country=country,
    )
    modem = Modem.new(hardware=hw)
    modem.state = state
    modem.last_used_at = last_used_at
    return modem


async def test_add_and_get_round_trip(session: AsyncSession) -> None:
    repo = PostgresModemRepository(session)
    modem = _make_modem(imei="111111111111111", iccid="89510041000000000001")

    await repo.add(modem)
    fetched = await repo.get(modem.id)

    assert fetched is not None
    assert fetched.hardware.imei == "111111111111111"
    assert fetched.country == Country.PE


async def test_get_unknown_returns_none(session: AsyncSession) -> None:
    repo = PostgresModemRepository(session)

    assert await repo.get("nope") is None


async def test_update_changes_state(session: AsyncSession) -> None:
    repo = PostgresModemRepository(session)
    modem = _make_modem(imei="222222222222222", iccid="89510041000000000002")
    await repo.add(modem)

    modem.assign()
    await repo.update(modem)

    refreshed = await repo.get(modem.id)
    assert refreshed is not None
    assert refreshed.state == ModemState.IN_USE
    assert refreshed.accounts_used_today == 1


async def test_update_unknown_raises(session: AsyncSession) -> None:
    repo = PostgresModemRepository(session)
    ghost = _make_modem(imei="000000000000000", iccid="89510041000000000099")

    with pytest.raises(DomainError):
        await repo.update(ghost)


async def test_list_by_country_returns_lru_first(session: AsyncSession) -> None:
    repo = PostgresModemRepository(session)
    pe_recent = _make_modem(
        imei="333333333333333",
        iccid="89510041000000000003",
        last_used_at=datetime(2026, 4, 27, 6, 0, tzinfo=UTC),
    )
    pe_old = _make_modem(
        imei="444444444444444",
        iccid="89510041000000000004",
        last_used_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    mx = _make_modem(
        imei="555555555555555",
        iccid="89510041000000000005",
        country=Country.MX,
    )
    for m in (pe_recent, pe_old, mx):
        await repo.add(m)

    pe_list = await repo.list_by_country(Country.PE)

    assert [m.hardware.imei for m in pe_list] == [
        "444444444444444",
        "333333333333333",
    ]
