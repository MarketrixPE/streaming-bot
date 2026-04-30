"""Pagina Artists: alta y administracion de artistas multi-tenant.

Lee directamente del ``IArtistRepository`` (Postgres/SQLite). Para enriquecer
con conteo de canciones, joinea en memoria con los targets del catalogo: es
barato porque ``state.repos`` ya cachea sesiones y la cardinalidad es baja
(decenas de artistas, cientos de canciones).
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from streaming_bot.domain.artist import Artist
from streaming_bot.domain.label import Label
from streaming_bot.domain.song import Song
from streaming_bot.presentation.dashboard.state import get_state


@st.cache_data(ttl=20, show_spinner=False)
def _load_artists_dataframe() -> pd.DataFrame:
    state = get_state()
    artists: list[Artist] = state.repos.list_artists()
    labels: list[Label] = state.repos.list_labels()
    songs: list[Song] = state.repos.list_target_songs()

    label_by_id = {label.id: label.name for label in labels}
    songs_by_artist_id: dict[str, int] = {}
    flag_by_artist_id: dict[str, bool] = {}
    for s in songs:
        if s.primary_artist_id is None:
            continue
        songs_by_artist_id[s.primary_artist_id] = songs_by_artist_id.get(s.primary_artist_id, 0) + 1
        if s.spike_oct2025_flag:
            flag_by_artist_id[s.primary_artist_id] = True

    rows: list[dict[str, object]] = []
    for a in artists:
        rows.append(
            {
                "name": a.name,
                "song_count": songs_by_artist_id.get(a.id, 0),
                "has_spike_history": flag_by_artist_id.get(a.id, a.has_spike_history),
                "label": label_by_id.get(a.label_id, a.label_id or "—") if a.label_id else "—",
                "primary_country": (a.primary_country.value if a.primary_country else ""),
                "status": a.status.value,
                "id": a.id,
            }
        )
    return pd.DataFrame(rows)


def render() -> None:
    state = get_state()
    st.title("Artistas")

    df = _load_artists_dataframe()

    total_artists = len(df)
    spike_artists = int(df["has_spike_history"].sum()) if not df.empty else 0
    total_songs = int(df["song_count"].sum()) if not df.empty else 0

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Total artistas", f"{total_artists}")
    col_b.metric("Con spike history", f"{spike_artists}")
    col_c.metric("Canciones totales", f"{total_songs}")

    st.divider()

    if df.empty:
        st.info(
            "Aun no hay canciones en el catalogo. Sube un archivo desde la "
            "pagina Import para empezar."
        )
    else:
        st.subheader(f"Listado ({total_artists})")
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "has_spike_history": st.column_config.CheckboxColumn("Spike history"),
            },
        )

    st.divider()

    st.subheader("Alta de artista")
    if "artist_actions_log" not in st.session_state:
        st.session_state["artist_actions_log"] = []

    with st.form("new_artist_form"):
        new_name = st.text_input(
            "Nombre del artista",
            placeholder="ej. Lu Andre",
        )
        new_country = st.text_input(
            "Pais primario (ISO 2 letras)",
            placeholder="ej. PE",
            max_chars=2,
        )
        new_label = st.text_input(
            "Label (opcional)",
            placeholder="ej. Worldwide Hits",
        )
        submitted = st.form_submit_button("Dar de alta", type="primary")

    if submitted:
        errors: list[str] = []
        if not new_name.strip():
            errors.append("El nombre del artista es obligatorio.")
        if new_country and len(new_country.strip()) != 2:
            errors.append("El codigo de pais debe ser ISO de 2 letras.")
        if errors:
            for e in errors:
                st.warning(e)
        else:
            entry = {
                "name": new_name.strip(),
                "country": new_country.strip().upper() or None,
                "label": new_label.strip() or None,
            }
            st.session_state["artist_actions_log"].append(("create", entry))
            st.success(
                "Artista registrado en cola local. La persistencia real "
                "requiere ``IArtistRepository`` postgres (EPIC 13)."
            )

    st.divider()
    st.subheader("Acciones rapidas (placeholder)")
    if df.empty:
        st.caption("Sin artistas para administrar.")
    else:
        sel = st.selectbox(
            "Artista",
            df["name"].tolist(),
        )
        col_pause, col_archive, col_reactivate = st.columns(3)
        with col_pause:
            if st.button("Pausar"):
                st.session_state["artist_actions_log"].append(("pause", sel))
                st.warning(f"{sel}: pause registrado en cola local.")
        with col_archive:
            if st.button("Archivar"):
                st.session_state["artist_actions_log"].append(("archive", sel))
                st.warning(f"{sel}: archive registrado en cola local.")
        with col_reactivate:
            if st.button("Reactivar"):
                st.session_state["artist_actions_log"].append(("reactivate", sel))
                st.success(f"{sel}: reactivate registrado en cola local.")

    if st.session_state["artist_actions_log"]:
        st.divider()
        st.subheader("Cola local de acciones (no persistida aun)")
        st.json(st.session_state["artist_actions_log"])

    if not df.empty:
        st.divider()
        st.subheader("Canciones por artista")
        top_n = df.sort_values("song_count", ascending=False).head(20)
        fig = px.bar(top_n, x="name", y="song_count", color="name")
        fig.update_layout(xaxis_tickangle=-45, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    # `state` se mantiene en uso para ergonomia futura (e.g. wire de repo)
    _ = state


render()
