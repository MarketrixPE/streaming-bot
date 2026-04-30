"""Pagina Modems: pool de modems 4G/5G."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from streaming_bot.presentation.dashboard.state import get_state


@st.cache_data(ttl=15, show_spinner=False)
def _load_modems_dataframe() -> pd.DataFrame:
    state = get_state()
    modems = state.repos.list_modems()
    rows: list[dict[str, object]] = []
    for m in modems:
        rows.append(
            {
                "id": m.id,
                "operator": m.hardware.operator,
                "country": m.hardware.sim_country.value,
                "state": m.state.value,
                "current_public_ip": m.current_public_ip or "",
                "accounts_used_today": m.accounts_used_today,
                "streams_served_today": m.streams_served_today,
                "flagged_count": m.flagged_count,
                "last_used_at": m.last_used_at.isoformat() if m.last_used_at else "",
                "available": m.is_available,
            }
        )
    return pd.DataFrame(rows)


def render() -> None:
    state = get_state()
    flags = state.flags_store.load()
    st.title("Modems")

    df = _load_modems_dataframe()
    if df.empty:
        st.info("No hay modems registrados en la base de datos.")
        return

    total = len(df)
    available = int(df["available"].sum())
    flagged = int((df["flagged_count"] > 0).sum())
    quarantined = int((df["state"] == "quarantined").sum())

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Total", f"{total}")
    col_b.metric("Disponibles", f"{available}")
    col_c.metric("Con flag", f"{flagged}")
    col_d.metric("Cuarentena", f"{quarantined}")

    st.divider()

    st.subheader("Listado")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if st.button("Force rotate (placeholder)"):
        flags = state.flags_store.mark_force_rotation()
        st.success(
            "Rotacion forzada registrada en flags. Cuando IModemPool exponga "
            "un puerto de rotacion sincrono, este boton lo invocara."
        )
        st.caption(f"Ultima rotacion forzada: {flags.last_force_rotation_at}")

    st.divider()

    st.subheader("Modems por estado")
    by_state = df.groupby("state", as_index=False).size().rename(columns={"size": "count"})
    fig = px.pie(by_state, names="state", values="count", hole=0.55)
    st.plotly_chart(fig, use_container_width=True)


render()
