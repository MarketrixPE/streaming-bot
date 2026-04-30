"""Tests del dominio puro."""

from __future__ import annotations

import pytest

from streaming_bot.domain.value_objects import Country, GeoCoordinate, ProxyEndpoint, StreamResult


class TestGeoCoordinate:
    def test_valid_construction(self) -> None:
        coord = GeoCoordinate(latitude=40.4, longitude=-3.7)
        assert coord.latitude == 40.4
        assert coord.longitude == -3.7

    @pytest.mark.parametrize("lat", [-90.1, 90.5, 1000])
    def test_invalid_latitude_raises(self, lat: float) -> None:
        with pytest.raises(ValueError, match="latitude"):
            GeoCoordinate(latitude=lat, longitude=0.0)

    @pytest.mark.parametrize("lon", [-180.1, 180.1, -999])
    def test_invalid_longitude_raises(self, lon: float) -> None:
        with pytest.raises(ValueError, match="longitude"):
            GeoCoordinate(latitude=0.0, longitude=lon)

    def test_is_frozen(self) -> None:
        coord = GeoCoordinate(latitude=0.0, longitude=0.0)
        with pytest.raises(AttributeError):
            coord.latitude = 1.0  # type: ignore[misc]


class TestProxyEndpoint:
    def test_valid_construction(self) -> None:
        proxy = ProxyEndpoint(scheme="http", host="example.com", port=8080)
        assert proxy.as_url() == "http://example.com:8080"

    def test_invalid_scheme_raises(self) -> None:
        with pytest.raises(ValueError, match="scheme"):
            ProxyEndpoint(scheme="ftp", host="x", port=21)

    @pytest.mark.parametrize("port", [0, -1, 65536, 999999])
    def test_invalid_port_raises(self, port: int) -> None:
        with pytest.raises(ValueError, match="port"):
            ProxyEndpoint(scheme="http", host="x", port=port)

    def test_country_optional(self) -> None:
        proxy = ProxyEndpoint(scheme="http", host="x", port=80, country=Country.ES)
        assert proxy.country == Country.ES


class TestStreamResult:
    def test_ok_factory(self) -> None:
        r = StreamResult.ok(account_id="a1", duration_ms=100)
        assert r.success
        assert r.account_id == "a1"
        assert r.error_message is None

    def test_failed_factory(self) -> None:
        r = StreamResult.failed(account_id="a1", duration_ms=100, error="boom")
        assert not r.success
        assert r.error_message == "boom"
