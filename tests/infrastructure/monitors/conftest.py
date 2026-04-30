"""Fixtures compartidos para los tests de monitores.

Provee:
- HTML cargado desde ``tests/fixtures/`` (mock realista pero no real).
- Fingerprint dummy.
- Logger structlog mockeable.
- ``FakeRichBrowserSession`` y ``FakeRichBrowserDriver`` que sirven HTML
  pregrabado por URL sin requerir Playwright real.
- ``BaselineCache`` con ruta temporal por test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import structlog

from streaming_bot.domain.value_objects import (
    Country,
    Fingerprint,
    GeoCoordinate,
    ProxyEndpoint,
)
from streaming_bot.infrastructure.monitors.baseline_cache import BaselineCache

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures"


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def fixture_distrokid_dashboard_html() -> str:
    return _read_fixture("distrokid_dashboard.html")


@pytest.fixture(scope="session")
def fixture_distrokid_dashboard_clean_html() -> str:
    return _read_fixture("distrokid_dashboard_clean.html")


@pytest.fixture(scope="session")
def fixture_distrokid_signin_html() -> str:
    return _read_fixture("distrokid_signin.html")


@pytest.fixture(scope="session")
def fixture_onerpm_dashboard_html() -> str:
    return _read_fixture("onerpm_dashboard.html")


@pytest.fixture(scope="session")
def fixture_onerpm_dashboard_clean_html() -> str:
    return _read_fixture("onerpm_dashboard_clean.html")


@pytest.fixture(scope="session")
def fixture_spotify_stats_html() -> str:
    return _read_fixture("spotify_for_artists_stats.html")


@pytest.fixture(scope="session")
def fixture_spotify_stats_clean_html() -> str:
    return _read_fixture("spotify_for_artists_clean.html")


@pytest.fixture()
def dummy_fingerprint() -> Fingerprint:
    return Fingerprint(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        ),
        locale="es-PE",
        timezone_id="America/Lima",
        geolocation=GeoCoordinate(latitude=-12.0464, longitude=-77.0428),
        country=Country.PE,
    )


@pytest.fixture()
def test_logger() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger("test_monitor")


@pytest.fixture()
def baseline_cache_tmp(tmp_path: Path, test_logger: structlog.stdlib.BoundLogger) -> BaselineCache:
    return BaselineCache(
        cache_path=tmp_path / "baseline.json",
        max_samples_per_metric=12,
        logger=test_logger,
    )


# ── Fakes de browser ──────────────────────────────────────────────────────────


@dataclass
class FakeRichBrowserSession:
    """Sesion fake que sirve HTML pregrabado por URL.

    Provee SOLO los metodos que los monitors usan. No implementa el contrato
    completo de IRichBrowserSession porque structlog/mypy no nos lo exigen
    en runtime y los tests no chequean el Protocol entero.
    """

    html_by_url: dict[str, str]
    storage_state_payload: dict[str, Any] = field(default_factory=dict)
    current_url_value: str = ""
    visible_selectors: set[str] = field(default_factory=set)
    raise_on_goto: dict[str, Exception] = field(default_factory=dict)
    last_url: str = ""
    visit_log: list[str] = field(default_factory=list)
    default_html: str = "<html><body></body></html>"

    async def goto(self, url: str, *, wait_until: str = "networkidle") -> None:
        _ = wait_until
        self.last_url = url
        # Si el test no preconfiguro una URL final (simulando redirect),
        # actualizamos current_url_value con la URL navegada. Si si la
        # preconfiguro, la respetamos para emular redirects de login, etc.
        if not self.current_url_value:
            self.current_url_value = url
        self.visit_log.append(url)
        if url in self.raise_on_goto:
            raise self.raise_on_goto[url]

    async def fill(self, selector: str, value: str) -> None:
        _ = selector, value

    async def click(self, selector: str) -> None:
        _ = selector

    async def wait_for_selector(self, selector: str, *, timeout_ms: int = 30000) -> None:
        _ = selector, timeout_ms

    async def evaluate(self, expression: str) -> Any:
        _ = expression
        return None

    async def screenshot(self, path: str) -> None:
        _ = path

    async def content(self) -> str:
        return self.html_by_url.get(self.last_url, self.default_html)

    async def storage_state(self) -> dict[str, Any]:
        return dict(self.storage_state_payload)

    async def current_url(self) -> str:
        return self.current_url_value

    async def is_visible(self, selector: str, *, timeout_ms: int = 1000) -> bool:
        _ = timeout_ms
        return selector in self.visible_selectors

    async def go_back(self) -> None: ...

    async def reload(self) -> None: ...

    async def human_click(
        self,
        selector: str,
        *,
        button: str = "left",
        click_count: int = 1,
        delay_ms_before: int = 0,
        offset_jitter_px: int = 5,
    ) -> None:
        _ = selector, button, click_count, delay_ms_before, offset_jitter_px

    async def human_mouse_move(
        self, x: int, y: int, *, duration_ms: int = 500, bezier_steps: int = 30
    ) -> None:
        _ = x, y, duration_ms, bezier_steps

    async def hover(self, selector: str, *, duration_ms: int = 200) -> None:
        _ = selector, duration_ms

    async def human_type(
        self,
        selector: str,
        text: str,
        *,
        wpm: int = 70,
        wpm_stddev: int = 15,
        typo_probability: float = 0.03,
    ) -> None:
        _ = selector, text, wpm, wpm_stddev, typo_probability

    async def press_key(self, key: str, *, count: int = 1, delay_ms: int = 80) -> None:
        _ = key, count, delay_ms

    async def human_scroll(
        self, *, direction: str = "down", pixels: int, duration_ms: int = 800
    ) -> None:
        _ = direction, pixels, duration_ms

    async def get_viewport_size(self) -> tuple[int, int]:
        return 1366, 768

    async def set_viewport_size(self, width: int, height: int) -> None:
        _ = width, height

    async def query_selector_count(self, selector: str) -> int:
        _ = selector
        return 0

    async def get_text(self, selector: str) -> str:
        _ = selector
        return ""

    async def get_bounding_box(self, selector: str) -> tuple[float, float, float, float] | None:
        _ = selector
        return None

    async def emulate_tab_blur(self, *, duration_ms: int) -> None:
        _ = duration_ms

    async def wait(self, ms: int) -> None:
        _ = ms


@dataclass
class FakeRichBrowserDriver:
    """Driver fake que entrega ``FakeRichBrowserSession`` con HTML por URL."""

    session_template: FakeRichBrowserSession

    @asynccontextmanager
    async def session(
        self,
        *,
        proxy: ProxyEndpoint | None,
        fingerprint: Fingerprint,
        storage_state: dict[str, Any] | None = None,
    ) -> AsyncIterator[FakeRichBrowserSession]:
        _ = proxy, fingerprint, storage_state
        # Devolvemos siempre la misma instancia para que los tests inspeccionen
        # ``visit_log`` despues. Los visit_log se reinician por test via fixture.
        yield self.session_template

    async def close(self) -> None:
        pass


@pytest.fixture()
def fake_browser_factory() -> Iterator[Any]:
    """Factory para construir el driver fake con el HTML que cada test necesite."""

    def _build(
        html_by_url: dict[str, str],
        *,
        storage_state: dict[str, Any] | None = None,
        visible_selectors: set[str] | None = None,
        current_url: str = "",
    ) -> tuple[FakeRichBrowserDriver, FakeRichBrowserSession]:
        session = FakeRichBrowserSession(
            html_by_url=dict(html_by_url),
            storage_state_payload=dict(storage_state or {}),
            visible_selectors=set(visible_selectors or set()),
            current_url_value=current_url,
        )
        return FakeRichBrowserDriver(session_template=session), session

    yield _build
