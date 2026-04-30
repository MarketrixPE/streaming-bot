"""Puerto para persistencia de labels (sellos / cuentas distribuidor)."""

from __future__ import annotations

from typing import Protocol

from streaming_bot.domain.label import DistributorType, Label, LabelHealth


class ILabelRepository(Protocol):
    """Repositorio para labels."""

    async def save(self, label: Label) -> None: ...

    async def get(self, label_id: str) -> Label | None: ...

    async def get_by_name(self, name: str) -> Label | None: ...

    async def list_by_distributor(self, distributor: DistributorType) -> list[Label]: ...

    async def list_by_health(self, health: LabelHealth) -> list[Label]: ...

    async def list_all(self) -> list[Label]: ...

    async def delete(self, label_id: str) -> None: ...
