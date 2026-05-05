"""Tests del router /v1/accounts (lista, detalle, health, anomaly_score)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from streaming_bot.config import Settings
from streaming_bot.domain.entities import Account, AccountStatus
from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.ml.anomaly_score import (
    AnomalyScore,
    FeatureContribution,
    RiskLevel,
)
from streaming_bot.domain.value_objects import Country
from streaming_bot.presentation.api.auth import JWTAuthValidator
from tests.presentation.conftest import build_app_with_overrides


def _account(
    *,
    account_id: str = "acc-1",
    state: str = "active",
    country: Country = Country.PE,
) -> Account:
    return Account(
        id=account_id,
        username=f"user-{account_id}",
        password="encrypted",
        country=country,
        status=AccountStatus(state=state),
        last_used_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_list_accounts(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    accounts_repo = AsyncMock()
    accounts_repo.all.return_value = [
        _account(account_id="a"),
        _account(account_id="b", state="banned"),
    ]
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        account_repo=accounts_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/accounts")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["state"] for item in body["items"]} == {"active", "banned"}


@pytest.mark.asyncio
async def test_list_accounts_filter_by_state(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    accounts_repo = AsyncMock()
    accounts_repo.all.return_value = [
        _account(account_id="a"),
        _account(account_id="b", state="banned"),
    ]
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        account_repo=accounts_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/accounts", params={"state": "banned"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["state"] == "banned"


@pytest.mark.asyncio
async def test_get_account_by_id(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    accounts_repo = AsyncMock()
    accounts_repo.get.return_value = _account(account_id="x")
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        account_repo=accounts_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/accounts/x")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "x"
    accounts_repo.get.assert_awaited_once_with("x")


@pytest.mark.asyncio
async def test_get_account_404(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    accounts_repo = AsyncMock()
    accounts_repo.get.side_effect = DomainError("cuenta no encontrada")
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        account_repo=accounts_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/accounts/missing")
    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "account_not_found"


@pytest.mark.asyncio
async def test_account_health_includes_streams_today(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    accounts_repo = AsyncMock()
    accounts_repo.get.return_value = _account(account_id="acc-h")
    history_repo = AsyncMock()
    history_repo.count_for_account_today.return_value = 7
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        account_repo=accounts_repo,
        stream_history_repo=history_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/accounts/acc-h/health")
    assert response.status_code == 200
    body = response.json()
    assert body["account_id"] == "acc-h"
    assert body["streams_today"] == 7
    assert body["is_usable"] is True
    history_repo.count_for_account_today.assert_awaited_once_with("acc-h")


@pytest.mark.asyncio
async def test_anomaly_score_disabled_when_no_predictor(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    accounts_repo = AsyncMock()
    accounts_repo.get.return_value = _account(account_id="acc-z")
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        account_repo=accounts_repo,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/accounts/acc-z/anomaly_score")
    assert response.status_code == 200
    body = response.json()
    assert body["model_version"] == "disabled"
    assert body["risk_level"] == "low"
    assert body["score"] == 0.0


@pytest.mark.asyncio
async def test_anomaly_score_with_predictor(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    accounts_repo = AsyncMock()
    accounts_repo.get.return_value = _account(account_id="acc-p")
    container = MagicMock()
    container.anomaly_predictor = MagicMock()
    container.anomaly_predictor.predict_for_account = AsyncMock(
        return_value=AnomalyScore(
            account_id="acc-p",
            score=0.92,
            risk_level=RiskLevel.CRITICAL,
            computed_at=datetime.now(UTC),
            top_features=(FeatureContribution("feat_a", 0.4),),
            model_version="v1.2",
        )
    )
    container.track_health_repository = None
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        account_repo=accounts_repo,
        container=container,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/accounts/acc-p/anomaly_score")
    assert response.status_code == 200
    body = response.json()
    assert body["risk_level"] == "critical"
    assert body["model_version"] == "v1.2"
    assert body["top_features"][0]["feature_name"] == "feat_a"
