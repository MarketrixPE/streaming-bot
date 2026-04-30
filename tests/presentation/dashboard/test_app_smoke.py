"""Smoke test del entry point Streamlit usando ``AppTest``.

Si ``streamlit.testing.v1`` no esta disponible, el test se salta.
"""

from __future__ import annotations

from pathlib import Path

import pytest

APP_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "streaming_bot"
    / "presentation"
    / "dashboard"
    / "app.py"
)


def test_app_main_renders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Carga ``app.py`` con ``AppTest`` y verifica que no explota."""
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest  # noqa: PLC0415 - import condicional

    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SB_DASHBOARD_FLAGS_PATH", str(tmp_path / "flags.json"))
    monkeypatch.setenv("SB_KILL_SWITCH_PATH", str(tmp_path / ".kill_switch_active"))
    monkeypatch.setenv("SB_KILL_SWITCH_AUDIT_PATH", str(tmp_path / "kill_switch_audit.log"))

    at = AppTest.from_file(str(APP_PATH), default_timeout=20)
    at.run()

    # El titulo debe renderizarse incluso si la DB esta vacia.
    titles = [t.value for t in at.title]
    assert any("Streaming Bot" in t for t in titles), titles
    # Sin excepciones inesperadas en el run.
    assert not at.exception, at.exception
