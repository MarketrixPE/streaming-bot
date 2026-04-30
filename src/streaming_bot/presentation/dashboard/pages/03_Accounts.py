"""Pagina Accounts: pool de cuentas listening."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from streaming_bot.presentation.dashboard.state import get_state


@st.cache_data(ttl=20, show_spinner=False)
def _load_accounts_dataframe() -> pd.DataFrame:
    state = get_state()
    accounts = state.repos.list_accounts()
    rows: list[dict[str, object]] = []
    for acc in accounts:
        rows.append(
            {
                "id": acc.id,
                "username": acc.username,
                "country": acc.country.value,
                "state": acc.status.state,
                "reason": acc.status.reason or "",
                "last_used_at": acc.last_used_at.isoformat() if acc.last_used_at else "",
            }
        )
    return pd.DataFrame(rows)


def render() -> None:
    st.title("Cuentas")

    df = _load_accounts_dataframe()
    if df.empty:
        st.info("No hay cuentas registradas en la base de datos.")
        return

    total = len(df)
    active = int((df["state"] == "active").sum())
    banned = int((df["state"] == "banned").sum())
    rate_limited = int((df["state"] == "rate_limited").sum())

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Total", f"{total}")
    col_b.metric("Activas", f"{active}")
    col_c.metric("Baneadas", f"{banned}")
    col_d.metric("Rate-limited", f"{rate_limited}")

    st.divider()

    countries_avail = sorted(df["country"].unique().tolist())
    states_avail = sorted(df["state"].unique().tolist())
    col_filter_a, col_filter_b = st.columns(2)
    with col_filter_a:
        country_sel = st.multiselect("Filtra por pais", countries_avail)
    with col_filter_b:
        state_sel = st.multiselect("Filtra por estado", states_avail)

    filtered = df.copy()
    if country_sel:
        filtered = filtered[filtered["country"].isin(country_sel)]
    if state_sel:
        filtered = filtered[filtered["state"].isin(state_sel)]

    st.subheader(f"Cuentas ({len(filtered)})")
    st.dataframe(filtered, use_container_width=True, hide_index=True)

    st.divider()

    st.subheader("Cuentas por pais")
    by_country = (
        df.groupby("country", as_index=False)
        .size()
        .rename(columns={"size": "count"})
        .sort_values("count", ascending=False)
    )
    fig = px.bar(by_country, x="country", y="count", color="country")
    st.plotly_chart(fig, use_container_width=True)


render()
