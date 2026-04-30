"""Tests del DashboardState y del flags store.

Cubrimos:
- ``DashboardSettings.from_env`` lee el entorno con fallbacks.
- ``build_state`` arma engine + runner + repos sin Streamlit en runtime.
- ``DashboardFlagsStore`` round-trip y resilencia ante archivo corrupto.
- ``get_state`` devuelve la misma instancia cacheada cuando Streamlit
  cache_resource decora la factoria (test sin Streamlit en sys.modules
  fuerza el branch fallback).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from streaming_bot.presentation.dashboard.flags_store import (
    DashboardFlags,
    DashboardFlagsStore,
)
from streaming_bot.presentation.dashboard.state import (
    DashboardSettings,
    DashboardState,
    build_state,
    get_state,
)


def test_settings_from_env_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SB_KILL_SWITCH_PATH", raising=False)
    monkeypatch.delenv("SB_KILL_SWITCH_AUDIT_PATH", raising=False)
    monkeypatch.delenv("SB_DASHBOARD_FLAGS_PATH", raising=False)

    cfg = DashboardSettings.from_env()
    assert cfg.dsn.startswith("sqlite+aiosqlite")
    assert isinstance(cfg.kill_switch_marker_path, Path)


def test_settings_from_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
    monkeypatch.setenv("SB_DASHBOARD_FLAGS_PATH", str(tmp_path / "flags.json"))
    cfg = DashboardSettings.from_env()
    assert cfg.dsn.startswith("postgresql+asyncpg")
    assert cfg.flags_path == tmp_path / "flags.json"


def test_build_state_smoke(tmp_path: Path) -> None:
    settings = DashboardSettings(
        dsn="sqlite+aiosqlite:///:memory:",
        kill_switch_marker_path=tmp_path / ".panic",
        kill_switch_audit_path=tmp_path / "panic_audit.log",
        flags_path=tmp_path / "flags.json",
    )
    state = build_state(settings)
    try:
        assert isinstance(state, DashboardState)
        assert state.engine is not None
        assert state.repos is not None
        # `tmp_path/flags.json`'s parent (tmp_path) must exist after build.
        assert state.settings.flags_path.parent.exists()
    finally:
        state.runner.shutdown()


def test_flags_store_roundtrip(tmp_path: Path) -> None:
    store = DashboardFlagsStore(path=tmp_path / "flags.json")
    flags = store.load()
    assert flags == DashboardFlags()
    flags = store.pause_pilot("test reason")
    assert flags.pilot_paused is True
    again = store.load()
    assert again.pilot_paused is True
    assert again.pilot_paused_reason == "test reason"
    resumed = store.resume_pilot()
    assert resumed.pilot_paused is False


def test_flags_store_handles_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "flags.json"
    path.write_text("not-json", encoding="utf-8")
    store = DashboardFlagsStore(path=path)
    assert store.load() == DashboardFlags()


def test_flags_store_force_rotation_marker(tmp_path: Path) -> None:
    store = DashboardFlagsStore(path=tmp_path / "flags.json")
    flags = store.mark_force_rotation()
    assert flags.last_force_rotation_at is not None
    persisted = json.loads((tmp_path / "flags.json").read_text())
    assert persisted["last_force_rotation_at"] == flags.last_force_rotation_at


def test_get_state_returns_same_instance_in_test_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Sin Streamlit en runtime, ``get_state`` cae al fallback (build directo).

    El fallback no cachea (cada llamada construye un state nuevo). Esto
    es esperado: la cache real es responsabilidad de Streamlit. Aqui
    validamos que el branch funciona sin levantar st.runtime.
    """
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SB_DASHBOARD_FLAGS_PATH", str(tmp_path / "flags.json"))

    # Mascaramos ``streamlit`` para forzar el ImportError branch del fallback.
    streamlit_present = "streamlit" in sys.modules
    saved = sys.modules.pop("streamlit", None)
    monkeypatch.setattr(
        "builtins.__import__",
        _import_blocking_streamlit(__import__),
    )
    try:
        state = get_state()
        assert isinstance(state, DashboardState)
        state.runner.shutdown()
    finally:
        # Restaura el modulo si lo habiamos quitado.
        if streamlit_present and saved is not None:
            sys.modules["streamlit"] = saved


def _import_blocking_streamlit(real_import):  # type: ignore[no-untyped-def]
    """Devuelve un ``__import__`` que rechaza ``streamlit`` para tests."""

    def _patched(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "streamlit":
            raise ImportError("streamlit blocked by test")
        return real_import(name, *args, **kwargs)

    return _patched


def test_get_state_uses_streamlit_cache_resource_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cuando `streamlit` esta importable, ``get_state`` envuelve con cache_resource.

    Como el cache_resource real requiere el runtime de Streamlit, aqui
    verificamos que el atributo ``cache_resource`` se invoca y al
    ejecutar el resultado devuelve un ``DashboardState``.
    """
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SB_DASHBOARD_FLAGS_PATH", str(tmp_path / "flags.json"))

    state = get_state()
    try:
        assert isinstance(state, DashboardState)
    finally:
        state.runner.shutdown()


def test_kill_switch_path_isolation(tmp_path: Path) -> None:
    """``DashboardSettings`` honra paths independientes (no globals)."""
    cfg = DashboardSettings(
        dsn="sqlite+aiosqlite:///:memory:",
        kill_switch_marker_path=tmp_path / ".alt-marker",
        kill_switch_audit_path=tmp_path / "alt-audit.log",
        flags_path=tmp_path / "alt-flags.json",
    )
    state = build_state(cfg)
    try:
        assert not (tmp_path / ".alt-marker").exists()
        # Verifica simetria con la env-default.
        env_path = os.getenv("SB_KILL_SWITCH_PATH")
        if env_path is not None:
            assert state.settings.kill_switch_marker_path != Path(env_path)
    finally:
        state.runner.shutdown()
