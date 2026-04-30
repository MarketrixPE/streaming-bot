"""Test del repo cifrado: round-trip + protección contra clave incorrecta."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from streaming_bot.domain.entities import Account
from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.repos import EncryptedAccountRepository


@pytest.fixture
def master_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def repo(tmp_path: Path, master_key: str) -> EncryptedAccountRepository:
    return EncryptedAccountRepository(
        path=tmp_path / "accounts.encrypted",
        master_key=master_key,
    )


class TestEncryptedAccountRepository:
    async def test_empty_returns_empty_list(self, repo: EncryptedAccountRepository) -> None:
        assert await repo.all() == []

    async def test_round_trip(self, repo: EncryptedAccountRepository) -> None:
        acc = Account.new(username="user@x.com", password="secret123", country=Country.ES)
        await repo.update(acc)

        all_accounts = await repo.all()
        assert len(all_accounts) == 1
        loaded = all_accounts[0]
        assert loaded.username == "user@x.com"
        assert loaded.password == "secret123"
        assert loaded.country == Country.ES

    async def test_get_by_id(self, repo: EncryptedAccountRepository) -> None:
        acc = Account.new(username="u", password="p", country=Country.US)
        await repo.update(acc)

        loaded = await repo.get(acc.id)
        assert loaded.id == acc.id

    async def test_import_plaintext(
        self,
        repo: EncryptedAccountRepository,
    ) -> None:
        n = await repo.import_plaintext(
            ["user1:pass1\n", "user2:pass2\n", "  \n", "invalid_line\n"],
            country=Country.MX,
        )
        assert n == 2
        all_accounts = await repo.all()
        assert {a.username for a in all_accounts} == {"user1", "user2"}
        assert all(a.country == Country.MX for a in all_accounts)

    async def test_wrong_master_key_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "accounts.encrypted"
        repo1 = EncryptedAccountRepository(path=path, master_key=Fernet.generate_key().decode())
        await repo1.update(Account.new(username="u", password="p", country=Country.ES))

        repo2 = EncryptedAccountRepository(path=path, master_key=Fernet.generate_key().decode())
        with pytest.raises(DomainError, match="master_key"):
            await repo2.all()

    def test_empty_master_key_raises(self, tmp_path: Path) -> None:
        with pytest.raises(DomainError, match="master_key"):
            EncryptedAccountRepository(
                path=tmp_path / "accounts.encrypted",
                master_key="",
            )
