"""Streamlit entry point del dashboard operacional.

Run:
    uv run streamlit run src/streaming_bot/presentation/dashboard/app.py

Diseno:
- Una sola entrada de configuracion (``st.set_page_config``).
- Sidebar con navegacion delegada a Streamlit multi-page (los archivos en
  ``pages/`` se descubren automaticamente).
- Header con KPIs globales reales para no dejar la home vacia.
- Inyeccion del estado via ``get_state()`` (cacheado por
  ``st.cache_resource``).
"""

from __future__ import annotations

import streamlit as st

from streaming_bot.presentation.dashboard.state import get_state


def render() -> None:
    """Renderiza la home del dashboard."""
    st.set_page_config(
        page_title="Streaming Bot — Operator",
        page_icon=":radio:",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    state = get_state()

    st.title("Streaming Bot — Panel del Operador")
    st.caption(
        "Vista unificada de catalogo, piloto, cuentas, modems, monitores, "
        "sesiones, import e artistas. Todas las acciones criticas requieren "
        "confirmacion explicita."
    )

    with st.sidebar:
        st.header("streaming-bot")
        st.caption(f"DSN: `{_mask_dsn(state.settings.dsn)}`")
        st.caption(f"Flags: `{state.settings.flags_path}`")
        kill_active = state.runner.run(state.kill_switch.is_active())
        if kill_active:
            st.error("PANIC ACTIVO")
        else:
            st.success("Operativo")
        st.divider()
        st.markdown(
            "Selecciona una pagina del menu lateral para empezar.\n\n"
            "- **Catalog**: songs y bulk actions\n"
            "- **Pilot**: plan diario\n"
            "- **Accounts / Modems / Monitors**: pools\n"
            "- **Sessions**: auditoria\n"
            "- **Import**: subir CSV/Excel\n"
            "- **Artists**: alta y administracion\n"
        )

    flags = state.flags_store.load()

    col_a, col_b, col_c, col_d = st.columns(4)
    try:
        active_targets = state.repos.count_active_targets()
    except Exception as exc:
        st.error(f"Error consultando catalogo: {exc}")
        active_targets = 0

    col_a.metric("Targets activos", f"{active_targets}")
    col_b.metric("Pilot pausado", "SI" if flags.pilot_paused else "NO")
    col_c.metric("Kill-switch", "ACTIVO" if kill_active else "OK")
    col_d.metric(
        "Ultima rotacion forzada",
        flags.last_force_rotation_at or "—",
    )

    st.divider()
    st.subheader("Estado rapido")
    st.markdown(
        "- Usa **Catalog** para revisar canciones y aplicar bulk-actions.\n"
        "- Usa **Pilot** para iniciar/pausar el ramp-up.\n"
        "- Usa **Monitors** para ver alertas de DistroKid/OneRPM/Spotify4Artists.\n"
        "- Usa **Import** para subir un Excel/CSV multi-artista nuevo.\n"
    )


def _mask_dsn(dsn: str) -> str:
    """Devuelve la DSN sin credenciales para mostrar en el sidebar."""
    if "@" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1) if "://" in dsn else ("", dsn)
    creds_host = rest.split("@", 1)[1]
    return f"{scheme}://***:***@{creds_host}"


render()
