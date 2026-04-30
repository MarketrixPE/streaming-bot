"""Persistencia de storage_state cifrado por cuenta. Skip de logins repetidos."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio
from cryptography.fernet import Fernet, InvalidToken

from streaming_bot.domain.exceptions import DomainError


class FileSessionStore:
    """Implementa ISessionStore guardando un archivo cifrado por cuenta."""

    def __init__(self, *, base_dir: Path, master_key: str) -> None:
        if not master_key:
            raise DomainError("master_key vacía para FileSessionStore")
        self._base_dir = base_dir
        self._fernet = Fernet(master_key.encode("utf-8"))

    async def load(self, account_id: str) -> dict[str, Any] | None:
        path = self._path_for(account_id)
        if not await anyio.Path(path).exists():
            return None
        async with await anyio.open_file(path, "rb") as f:
            blob = await f.read()
        try:
            decrypted = self._fernet.decrypt(blob)
        except InvalidToken:
            return None  # archivo de otra clave; mejor regenerar.
        data: dict[str, Any] = json.loads(decrypted.decode("utf-8"))
        return data

    async def save(self, account_id: str, state: dict[str, Any]) -> None:
        path = self._path_for(account_id)
        await anyio.Path(path.parent).mkdir(parents=True, exist_ok=True)
        encrypted = self._fernet.encrypt(json.dumps(state).encode("utf-8"))
        async with await anyio.open_file(path, "wb") as f:
            await f.write(encrypted)

    async def delete(self, account_id: str) -> None:
        path = anyio.Path(self._path_for(account_id))
        if await path.exists():
            await path.unlink()

    def _path_for(self, account_id: str) -> Path:
        return self._base_dir / f"{account_id}.session"
