"""Test del caso de uso con TODOS los puertos mockeados.

Demuestra el valor de Clean Architecture: testeamos toda la lógica de
orquestación SIN abrir un browser, sin red, sin disco.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from streaming_bot.application.stream_song import (
    ISiteStrategy,
    StreamSongRequest,
    StreamSongUseCase,
)
from streaming_bot.domain.entities import Account, AccountStatus
from streaming_bot.domain.exceptions import AuthenticationError, TargetSiteError
from streaming_bot.domain.value_objects import (
    Country,
    Fingerprint,
    GeoCoordinate,
    ProxyEndpoint,
)


def _account(*, banned: bool = False) -> Account:
    acc = Account.new(username="u", password="p", country=Country.ES)
    if banned:
        acc.status = AccountStatus.banned("test")
    return acc


def _fingerprint() -> Fingerprint:
    return Fingerprint(
        user_agent="UA",
        locale="es-ES",
        timezone_id="Europe/Madrid",
        geolocation=GeoCoordinate(40.4, -3.7),
        country=Country.ES,
    )


@pytest.fixture
def fake_account() -> Account:
    return _account()


@pytest.fixture
def mocks(fake_account: Account) -> dict[str, Any]:
    """Crea mocks para todos los puertos."""
    accounts = AsyncMock()
    accounts.get.return_value = fake_account
    accounts.update.return_value = None

    sessions = AsyncMock()
    sessions.load.return_value = None
    sessions.save.return_value = None
    sessions.delete.return_value = None

    proxies = AsyncMock()
    proxies.acquire.return_value = ProxyEndpoint(
        scheme="http",
        host="proxy.test",
        port=8080,
        country=Country.ES,
    )
    proxies.report_success.return_value = None
    proxies.report_failure.return_value = None

    fingerprints = MagicMock()
    fingerprints.coherent_for.return_value = _fingerprint()

    page = AsyncMock()
    page.storage_state.return_value = {"cookies": []}

    @asynccontextmanager
    async def fake_session(**_kwargs: Any):
        yield page

    browser = MagicMock()
    browser.session = fake_session

    strategy = AsyncMock(spec=ISiteStrategy)
    strategy.is_logged_in.return_value = False
    strategy.login.return_value = None
    strategy.perform_action.return_value = None

    return {
        "accounts": accounts,
        "sessions": sessions,
        "proxies": proxies,
        "fingerprints": fingerprints,
        "browser": browser,
        "strategy": strategy,
        "page": page,
    }


@pytest.fixture
def use_case(mocks: dict[str, Any]) -> StreamSongUseCase:
    return StreamSongUseCase(
        browser=mocks["browser"],
        accounts=mocks["accounts"],
        proxies=mocks["proxies"],
        fingerprints=mocks["fingerprints"],
        sessions=mocks["sessions"],
        strategy=mocks["strategy"],
        logger=structlog.get_logger("test"),
    )


class TestStreamSongUseCase:
    async def test_happy_path_logs_in_and_saves_session(
        self,
        use_case: StreamSongUseCase,
        mocks: dict[str, Any],
        fake_account: Account,
    ) -> None:
        result = await use_case.execute(
            StreamSongRequest(account_id=fake_account.id, target_url="https://x"),
        )

        assert result.success
        mocks["strategy"].login.assert_awaited_once()
        mocks["sessions"].save.assert_awaited_once()
        mocks["strategy"].perform_action.assert_awaited_once()
        mocks["proxies"].report_success.assert_awaited_once()

    async def test_skip_login_when_already_logged_in(
        self,
        use_case: StreamSongUseCase,
        mocks: dict[str, Any],
        fake_account: Account,
    ) -> None:
        mocks["strategy"].is_logged_in.return_value = True

        await use_case.execute(
            StreamSongRequest(account_id=fake_account.id, target_url="https://x"),
        )

        mocks["strategy"].login.assert_not_awaited()
        mocks["sessions"].save.assert_not_awaited()

    async def test_banned_account_is_skipped(
        self,
        use_case: StreamSongUseCase,
        mocks: dict[str, Any],
    ) -> None:
        banned = _account(banned=True)
        mocks["accounts"].get.return_value = banned

        result = await use_case.execute(
            StreamSongRequest(account_id=banned.id, target_url="https://x"),
        )

        assert not result.success
        assert result.error_message and "account_not_usable" in result.error_message
        # No se debe haber adquirido proxy (early return)
        mocks["proxies"].acquire.assert_not_called()
        mocks["strategy"].is_logged_in.assert_not_called()

    async def test_authentication_error_deactivates_account(
        self,
        use_case: StreamSongUseCase,
        mocks: dict[str, Any],
        fake_account: Account,
    ) -> None:
        mocks["strategy"].login.side_effect = AuthenticationError("captcha")

        result = await use_case.execute(
            StreamSongRequest(account_id=fake_account.id, target_url="https://x"),
        )

        assert not result.success
        mocks["sessions"].delete.assert_awaited_once_with(fake_account.id)
        # update se llama con la cuenta marcada como banned
        updated_arg: Account = mocks["accounts"].update.await_args.args[0]
        assert updated_arg.status.state == "banned"

    async def test_transient_error_reports_proxy_failure(
        self,
        use_case: StreamSongUseCase,
        mocks: dict[str, Any],
        fake_account: Account,
    ) -> None:
        mocks["strategy"].perform_action.side_effect = TargetSiteError("layout cambió")

        result = await use_case.execute(
            StreamSongRequest(account_id=fake_account.id, target_url="https://x"),
        )

        assert not result.success
        mocks["proxies"].report_failure.assert_awaited_once()
