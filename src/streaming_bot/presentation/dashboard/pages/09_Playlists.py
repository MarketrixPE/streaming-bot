"""Pagina Playlists: composicion y sincronizacion de playlists."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streaming_bot.domain.playlist import PlaylistKind
from streaming_bot.presentation.dashboard.state import get_state


@st.cache_data(ttl=20, show_spinner=False)
def _load_playlists_by_kind(kind: str) -> pd.DataFrame:
    state = get_state()
    pk = PlaylistKind(kind)
    playlists = state.repos.list_playlists_by_kind(pk)
    rows: list[dict[str, object]] = []
    for p in playlists:
        rows.append(
            {
                "id": p.id,
                "spotify_id": p.spotify_id or "-",
                "name": p.name,
                "kind": p.kind.value,
                "owner": p.owner_account_id or "-",
                "territory": p.territory.value if p.territory else "-",
                "genre": p.genre or "-",
                "total_tracks": p.total_tracks,
                "target_count": len(p.target_tracks),
                "target_ratio": f"{p.target_ratio:.2f}",
                "follower_count": p.follower_count,
                "last_synced": (p.last_synced_at.isoformat() if p.last_synced_at else "-"),
            }
        )
    return pd.DataFrame(rows)


def render() -> None:
    st.title("Playlists")

    tabs = st.tabs(["Project Public", "Personal Private", "Camouflage Genre"])

    with tabs[0]:
        st.subheader("Project Public Playlists")
        df = _load_playlists_by_kind("project_public")
        if df.empty:
            st.info("No hay playlists publicas de proyecto.")
        else:
            st.metric("Total", len(df))
            st.dataframe(df, use_container_width=True, hide_index=True)

    with tabs[1]:
        st.subheader("Personal Private Playlists")
        df = _load_playlists_by_kind("personal_private")
        if df.empty:
            st.info("No hay playlists personales privadas.")
        else:
            st.metric("Total", len(df))
            st.dataframe(df, use_container_width=True, hide_index=True)

    with tabs[2]:
        st.subheader("Camouflage Genre Playlists")
        df = _load_playlists_by_kind("camouflage_genre")
        if df.empty:
            st.info("No hay playlists de camuflaje por genero.")
        else:
            st.metric("Total", len(df))
            st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    st.subheader("Composer rapido")
    st.info(
        "Composicion de playlists requiere acceso a DefaultPlaylistComposer "
        "y SpotifyWebApiClient. Usa el CLI para componer playlists: "
        "`streaming-bot playlist compose-personal` o `compose-project`."
    )


render()
