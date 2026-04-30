"""Estado global del dashboard cacheado por sesion de Streamlit.

`DashboardState` empaqueta:
- Settings (DSN, paths a kill-switch y flags).
- Engine asincrono + session_factory.
- AsyncRunner (loop dedicado).
- Adapter sincrono de repos.
- Stores de flags y kill-switch.

Se construye una sola vez via `get_state()` que internamente usa
`@st.cache_resource`, por lo que el engine vive durante toda la sesion
del proceso de Streamlit.

Diseño:
- El DSN se lee de ``DATABASE_URL`` (mismo nombre que Alembic) o cae al
  default sqlite local. Esto permite operar con Postgres en prod o SQLite
  para desarrollo sin cambios de codigo.
- El kill-switch usa la implementacion existente
  ``FilesystemPanicKillSwitch`` para mantener compat con el orchestrator.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from streaming_bot.infrastructure.monitors.panic_kill_switch import (
    FilesystemPanicKillSwitch,
)
from streaming_bot.infrastructure.persistence.postgres.database import (
    make_engine,
    make_session_factory,
)
from streaming_bot.presentation.dashboard.flags_store import DashboardFlagsStore
from streaming_bot.presentation.dashboard.repos_adapter import (
    AsyncRunner,
    SyncReposAdapter,
)

DEFAULT_DSN = "sqlite+aiosqlite:///./data/streaming_bot.db"
DEFAULT_KILL_SWITCH_PATH = Path("./.kill_switch_active")
DEFAULT_KILL_AUDIT_PATH = Path("./kill_switch_audit.log")
DEFAULT_FLAGS_PATH = Path("./data/dashboard_flags.json")


@dataclass(slots=True)
class DashboardSettings:
    """Configuracion del dashboard inyectable y testeable.

    Attributes:
        dsn: DSN async para SQLAlchemy. ``DATABASE_URL`` si esta seteada,
            o ``sqlite+aiosqlite`` local por defecto.
        kill_switch_marker_path: archivo marker del kill-switch.
        kill_switch_audit_path: log append-only del kill-switch.
        flags_path: archivo JSON donde persisten flags del operador.
    """

    dsn: str = DEFAULT_DSN
    kill_switch_marker_path: Path = DEFAULT_KILL_SWITCH_PATH
    kill_switch_audit_path: Path = DEFAULT_KILL_AUDIT_PATH
    flags_path: Path = DEFAULT_FLAGS_PATH

    @classmethod
    def from_env(cls) -> DashboardSettings:
        """Lee settings desde el entorno con fallbacks razonables."""
        return cls(
            dsn=os.getenv("DATABASE_URL", DEFAULT_DSN),
            kill_switch_marker_path=Path(
                os.getenv("SB_KILL_SWITCH_PATH", str(DEFAULT_KILL_SWITCH_PATH))
            ),
            kill_switch_audit_path=Path(
                os.getenv("SB_KILL_SWITCH_AUDIT_PATH", str(DEFAULT_KILL_AUDIT_PATH))
            ),
            flags_path=Path(os.getenv("SB_DASHBOARD_FLAGS_PATH", str(DEFAULT_FLAGS_PATH))),
        )


@dataclass(slots=True)
class DashboardState:
    """Estado vivo del dashboard. Solo campos cacheables.

    No agregar aqui nada por-request; usar ``st.session_state`` para eso.
    """

    settings: DashboardSettings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    runner: AsyncRunner
    repos: SyncReposAdapter
    kill_switch: FilesystemPanicKillSwitch
    flags_store: DashboardFlagsStore


def build_state(settings: DashboardSettings | None = None) -> DashboardState:
    """Construye un ``DashboardState`` real (sin Streamlit, util en tests).

    Esta funcion es la que envuelve ``st.cache_resource`` en ``app.py``.
    Mantenerla pura facilita testear el wiring sin levantar Streamlit.
    """
    cfg = settings or DashboardSettings.from_env()
    cfg.flags_path.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(cfg.dsn)
    factory = make_session_factory(engine)
    runner = AsyncRunner()
    repos = SyncReposAdapter(session_factory=factory, runner=runner)
    kill_switch = FilesystemPanicKillSwitch(
        marker_path=cfg.kill_switch_marker_path,
        audit_log_path=cfg.kill_switch_audit_path,
        logger=cast(Any, structlog.get_logger("dashboard.kill_switch")),
    )
    flags_store = DashboardFlagsStore(path=cfg.flags_path)
    return DashboardState(
        settings=cfg,
        engine=engine,
        session_factory=factory,
        runner=runner,
        repos=repos,
        kill_switch=kill_switch,
        flags_store=flags_store,
    )


def get_state() -> DashboardState:
    """Devuelve el ``DashboardState`` cacheado por Streamlit.

    Usa ``st.cache_resource`` para reutilizar engine/loop entre re-runs.
    Si Streamlit no esta disponible (tests sin runtime), construye el
    state directamente.
    """
    try:
        import streamlit as st  # noqa: PLC0415 - import opcional para fallback
    except ImportError:
        return build_state()

    @st.cache_resource(show_spinner=False)
    def _cached() -> DashboardState:
        return build_state()

    cached: DashboardState = _cached()
    return cached
