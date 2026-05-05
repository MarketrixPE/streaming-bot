"""Tests del router /v1/metrics (summary, streams_by_dsp, anomalies/active)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from streaming_bot.config import Settings
from streaming_bot.domain.ml.anomaly_score import AnomalyScore, RiskLevel
from streaming_bot.presentation.api.auth import JWTAuthValidator
from tests.presentation.conftest import build_app_with_overrides


def _scalar_returning(values: list[int]) -> AsyncMock:
    """AsyncMock que devuelve valores en orden por cada llamada a session.scalar."""
    iterator = iter(values)
    return AsyncMock(side_effect=lambda *_args, **_kwargs: next(iterator, 0))


@pytest.mark.asyncio
async def test_metrics_summary_aggregates_counters(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    session = AsyncMock()
    # 8 scalars en orden: accounts_total, accounts_active, songs_total,
    # songs_active_targets, artists_total, labels_total, sessions_today,
    # streams_counted_today.
    session.scalar = _scalar_returning([100, 80, 50, 30, 12, 4, 5, 21])
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        session=session,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/metrics/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["accounts_total"] == 100
    assert body["accounts_active"] == 80
    assert body["songs_total"] == 50
    assert body["songs_active_targets"] == 30
    assert body["artists_total"] == 12
    assert body["labels_total"] == 4
    assert body["sessions_today"] == 5
    assert body["streams_counted_today"] == 21


@pytest.mark.asyncio
async def test_streams_by_dsp_default_window(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=42)
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        session=session,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/metrics/streams_by_dsp")
    assert response.status_code == 200
    body = response.json()
    assert body["window"] == "today"
    assert body["by_dsp"] == {"spotify": 42}


@pytest.mark.asyncio
async def test_streams_by_dsp_invalid_window_returns_422(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=0)
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        session=session,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/metrics/streams_by_dsp", params={"window": "yesterday"})
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "validation_error"


@pytest.mark.asyncio
async def test_active_anomalies_empty_without_predictor(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    session = AsyncMock()
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        session=session,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/metrics/anomalies/active")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_active_anomalies_with_predictor(
    fake_settings: Settings,
    fake_validator: JWTAuthValidator,
    make_user,
) -> None:
    # Stub session.execute para devolver dos cuentas activas.
    session = AsyncMock()
    rows = MagicMock()
    rows.all.return_value = [("acc-a", "user-a"), ("acc-b", "user-b")]
    session.execute = AsyncMock(return_value=rows)

    container = MagicMock()
    container.anomaly_predictor = MagicMock()
    container.anomaly_predictor.predict_batch = AsyncMock(
        return_value=[
            AnomalyScore(
                account_id="acc-a",
                score=0.92,
                risk_level=RiskLevel.CRITICAL,
                computed_at=datetime.now(UTC),
                model_version="v1",
            ),
            AnomalyScore(
                account_id="acc-b",
                score=0.20,
                risk_level=RiskLevel.LOW,
                computed_at=datetime.now(UTC),
                model_version="v1",
            ),
        ]
    )
    container.track_health_repository = None
    app = build_app_with_overrides(
        settings=fake_settings,
        validator=fake_validator,
        user=make_user(),
        session=session,
        container=container,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/v1/metrics/anomalies/active")
    assert response.status_code == 200
    alerts = response.json()
    # Solo HIGH/CRITICAL debe aparecer.
    assert len(alerts) == 1
    assert alerts[0]["account_id"] == "acc-a"
    assert alerts[0]["risk_level"] == "critical"
    assert alerts[0]["username"] == "user-a"
