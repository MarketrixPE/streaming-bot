"""Tests del router /health y /readyz (no requieren auth ni rate limit)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint_responds_ok(api_client: AsyncClient) -> None:
    response = await api_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["component_checks"]["process"] == "ok"


@pytest.mark.asyncio
async def test_health_propagates_request_id_header(api_client: AsyncClient) -> None:
    custom_id = "0123456789abcdef0123456789abcdef"
    response = await api_client.get("/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_id


@pytest.mark.asyncio
async def test_readyz_returns_ok_with_session(api_client: AsyncClient) -> None:
    response = await api_client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["component_checks"]["database"] == "ok"


@pytest.mark.asyncio
async def test_health_is_not_documented_under_v1_prefix(api_client: AsyncClient) -> None:
    response = await api_client.get("/v1/health")
    assert response.status_code == 404
