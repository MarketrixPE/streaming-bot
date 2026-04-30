"""Pagina Camouflage: pool de canciones de camuflaje."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from streaming_bot.presentation.dashboard.state import get_state


@st.cache_data(ttl=60, show_spinner=False)
def _load_camouflage_stats() -> dict[str, object]:
    state = get_state()
    total = state.repos.count_camouflage_tracks()
    genres = state.repos.list_camouflage_genres()
    return {
        "total": total,
        "genres": genres,
        "unique_genres": len(genres),
    }


def render() -> None:
    st.title("Pool de Camuflaje")

    stats = _load_camouflage_stats()

    col_a, col_b = st.columns(2)
    col_a.metric("Total tracks", str(stats["total"]))
    col_b.metric("Generos unicos", str(stats["unique_genres"]))

    st.divider()

    st.subheader("Distribucion por genero")
    genres: list[tuple[str, int]] = stats["genres"]  # type: ignore[assignment]
    if not genres:
        st.info("No hay tracks de camuflaje en el pool.")
    else:
        df_genre = pd.DataFrame(genres, columns=["genero", "count"])
        fig_bar = px.bar(
            df_genre,
            x="genero",
            y="count",
            color="genero",
            title="Tracks por genero",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        fig_pie = px.pie(
            df_genre,
            names="genero",
            values="count",
            title="Proporcion por genero",
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    st.divider()

    st.subheader("Refresh pool")
    with st.form("refresh_pool_form"):
        _markets_input = st.text_input(
            "Mercados (separados por coma)",
            value="PE,MX,CL,AR,CO,ES",
            help="Ejemplo: PE,MX,CL,AR,CO,ES",
        )
        submit = st.form_submit_button("Refresh pool")

        if submit:
            st.warning(
                "Refresh de pool requiere SpotifyWebApiClient y CamouflageIngestService. "
                "Usa el CLI: `streaming-bot camouflage refresh --markets PE,MX,CL`"
            )


render()
