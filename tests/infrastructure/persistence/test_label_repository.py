"""Tests para PostgresLabelRepository."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from streaming_bot.domain.label import DistributorType, Label, LabelHealth
from streaming_bot.infrastructure.persistence.postgres.repos.label_repository import (
    PostgresLabelRepository,
)


def _make_label(
    *,
    name: str = "Worldwide Hits",
    distributor: DistributorType = DistributorType.AICOM,
) -> Label:
    return Label.new(
        name=name,
        distributor=distributor,
        owner_email="ops@example.com",
    )


async def test_save_and_get(session: AsyncSession) -> None:
    repo = PostgresLabelRepository(session)
    label = _make_label()
    await repo.save(label)

    fetched = await repo.get(label.id)

    assert fetched is not None
    assert fetched.name == "Worldwide Hits"
    assert fetched.distributor == DistributorType.AICOM


async def test_save_idempotent_updates_health(session: AsyncSession) -> None:
    repo = PostgresLabelRepository(session)
    label = _make_label()
    await repo.save(label)

    label.update_health(LabelHealth.WARNING, "minor warning")
    await repo.save(label)

    fetched = await repo.get(label.id)
    assert fetched is not None
    assert fetched.health == LabelHealth.WARNING
    assert fetched.notes == "minor warning"
    assert fetched.last_health_check is not None


async def test_get_by_name(session: AsyncSession) -> None:
    repo = PostgresLabelRepository(session)
    label = _make_label(name="Custom Sello")
    await repo.save(label)

    fetched = await repo.get_by_name("Custom Sello")

    assert fetched is not None
    assert fetched.id == label.id


async def test_list_by_distributor(session: AsyncSession) -> None:
    repo = PostgresLabelRepository(session)
    l1 = _make_label(name="A", distributor=DistributorType.DISTROKID)
    l2 = _make_label(name="B", distributor=DistributorType.AICOM)
    l3 = _make_label(name="C", distributor=DistributorType.DISTROKID)
    for label in (l1, l2, l3):
        await repo.save(label)

    distrokid = await repo.list_by_distributor(DistributorType.DISTROKID)
    aicom = await repo.list_by_distributor(DistributorType.AICOM)

    assert {x.name for x in distrokid} == {"A", "C"}
    assert {x.name for x in aicom} == {"B"}


async def test_list_by_health(session: AsyncSession) -> None:
    repo = PostgresLabelRepository(session)
    healthy = _make_label(name="H")
    warning = _make_label(name="W")
    warning.update_health(LabelHealth.WARNING, "test")
    await repo.save(healthy)
    await repo.save(warning)

    warns = await repo.list_by_health(LabelHealth.WARNING)

    assert len(warns) == 1
    assert warns[0].name == "W"


async def test_list_all_orders_by_name(session: AsyncSession) -> None:
    repo = PostgresLabelRepository(session)
    await repo.save(_make_label(name="Zeta"))
    await repo.save(_make_label(name="Alfa"))

    listed = await repo.list_all()

    assert [x.name for x in listed] == ["Alfa", "Zeta"]


async def test_delete_removes(session: AsyncSession) -> None:
    repo = PostgresLabelRepository(session)
    label = _make_label()
    await repo.save(label)

    await repo.delete(label.id)
    fetched = await repo.get(label.id)

    assert fetched is None


async def test_is_safe_to_operate_property() -> None:
    label = _make_label()
    assert label.is_safe_to_operate

    label.update_health(LabelHealth.WARNING, "")
    assert label.is_safe_to_operate

    label.update_health(LabelHealth.SUSPENDED, "")
    assert not label.is_safe_to_operate
