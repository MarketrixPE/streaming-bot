"""Dashboard Streamlit operacional del streaming-bot.

Esta capa de presentacion reune todas las vistas humanas:
catalogo, piloto, cuentas, modems, monitores, sesiones,
import de Excel/CSV, y administracion de artistas.

Reglas Clean Architecture:
- Solo importa de `domain` y `infrastructure` via adapters de repos.
- Sin logica de negocio aqui: las acciones invocan use-cases existentes
  o stubs que otros equipos completaran (ej. EPIC 13 ImportCatalog).
"""

from streaming_bot.presentation.dashboard.flags_store import (
    DashboardFlags,
    DashboardFlagsStore,
)
from streaming_bot.presentation.dashboard.repos_adapter import SyncReposAdapter
from streaming_bot.presentation.dashboard.state import DashboardSettings, DashboardState

__all__ = [
    "DashboardFlags",
    "DashboardFlagsStore",
    "DashboardSettings",
    "DashboardState",
    "SyncReposAdapter",
]
