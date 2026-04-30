"""Repositorio de cuentas cifrado con Fernet (AES-128-CBC + HMAC).

Formato del archivo en disco: 1 línea = 1 cuenta cifrada (token Fernet base64).
Decodificada: JSON con campos {id, username, password, country, status, last_used_at}.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
from cryptography.fernet import Fernet, InvalidToken

from streaming_bot.domain.entities import Account, AccountStatus
from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.value_objects import Country

if TYPE_CHECKING:
    from collections.abc import Iterable


class EncryptedAccountRepository:
    """Implementa IAccountRepository persistiendo cuentas cifradas en archivo."""

    def __init__(self, *, path: Path, master_key: str) -> None:
        if not master_key:
            raise DomainError(
                "master_key vacía. Genera una con: "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"',
            )
        self._path = path
        self._fernet = Fernet(master_key.encode("utf-8"))

    async def all(self) -> list[Account]:
        return list(await self._read_all())

    async def get(self, account_id: str) -> Account:
        for acc in await self._read_all():
            if acc.id == account_id:
                return acc
        raise DomainError(f"cuenta no encontrada: {account_id}")

    async def update(self, account: Account) -> None:
        accounts = list(await self._read_all())
        for i, existing in enumerate(accounts):
            if existing.id == account.id:
                accounts[i] = account
                break
        else:
            accounts.append(account)
        await self._write_all(accounts)

    async def import_plaintext(self, lines: Iterable[str], country: Country) -> int:
        """Migra de formato `username:password` plano (como `accounts.txt` original)."""
        new_accounts: list[Account] = []
        for raw in lines:
            line = raw.strip()
            if not line or ":" not in line:
                continue
            user, _, pwd = line.partition(":")
            new_accounts.append(Account.new(username=user, password=pwd, country=country))
        existing = await self._read_all()
        await self._write_all([*existing, *new_accounts])
        return len(new_accounts)

    # -- internos --------------------------------------------------------- #

    async def _read_all(self) -> list[Account]:
        if not await anyio.Path(self._path).exists():
            return []
        async with await anyio.open_file(self._path, "rb") as f:
            content = await f.read()
        accounts: list[Account] = []
        for raw_line in content.splitlines():
            if not raw_line.strip():
                continue
            try:
                decrypted = self._fernet.decrypt(raw_line)
            except InvalidToken as exc:
                raise DomainError("master_key incorrecta o archivo corrupto") from exc
            payload: dict[str, Any] = json.loads(decrypted.decode("utf-8"))
            accounts.append(self._from_dict(payload))
        return accounts

    async def _write_all(self, accounts: list[Account]) -> None:
        await anyio.Path(self._path.parent).mkdir(parents=True, exist_ok=True)
        lines: list[bytes] = []
        for acc in accounts:
            payload = json.dumps(self._to_dict(acc), separators=(",", ":"))
            lines.append(self._fernet.encrypt(payload.encode("utf-8")))
        async with await anyio.open_file(self._path, "wb") as f:
            await f.write(b"\n".join(lines))

    @staticmethod
    def _to_dict(acc: Account) -> dict[str, Any]:
        return {
            "id": acc.id,
            "username": acc.username,
            "password": acc.password,
            "country": acc.country.value,
            "status": acc.status.state,
            "status_reason": acc.status.reason,
            "last_used_at": acc.last_used_at.isoformat() if acc.last_used_at else None,
        }

    @staticmethod
    def _from_dict(payload: dict[str, Any]) -> Account:
        status_state = payload.get("status", "active")
        if status_state == "banned":
            status = AccountStatus.banned(payload.get("status_reason") or "")
        elif status_state == "rate_limited":
            status = AccountStatus.rate_limited(payload.get("status_reason") or "")
        else:
            status = AccountStatus.active()
        last_used_raw: str | None = payload.get("last_used_at")
        return Account(
            id=payload["id"],
            username=payload["username"],
            password=payload["password"],
            country=Country(payload["country"]),
            status=status,
            last_used_at=datetime.fromisoformat(last_used_raw) if last_used_raw else None,
        )
