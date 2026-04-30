"""Pagina Catalog: vista de todas las canciones target con bulk actions.

Operaciones:
- Filtros (artista, tier, pilot-eligible, FLAGGED, busqueda).
- Bulk: toggle is_active, cambiar tier, marcar protegido, excluir piloto.
- Charts plotly: distribucion por tier + top remaining capacity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd
import plotly.express as px
import streamlit as st

from streaming_bot.domain.song import Song, SongTier
from streaming_bot.presentation.dashboard.state import DashboardState, get_state


@dataclass(frozen=True, slots=True)
class CatalogRow:
    """Vista plana de una cancion para la tabla del operador."""

    spotify_uri: str
    title: str
    artist: str
    label: str
    tier: str
    baseline: float
    target: int
    today_count: int
    progress_pct: float
    is_active: bool
    flagged: bool
    pilot_eligible: bool


def _display_tier(song: Song) -> str:
    """Tier de display que combina dominio + heuristica por baseline.

    El campo `Song.tier` viaja al dominio pero el backend Postgres aun no
    persiste tier en columna; mientras tanto usamos baseline como proxy.
    Si `tier` es distinto del default MID, lo respetamos.
    """
    if song.spike_oct2025_flag:
        return str(SongTier.FLAGGED.value)
    if song.tier != SongTier.MID:
        return str(song.tier.value)
    if song.baseline_streams_per_day < 10:
        return str(SongTier.ZOMBIE.value)
    if song.baseline_streams_per_day < 100:
        return str(SongTier.LOW.value)
    if song.baseline_streams_per_day < 500:
        return str(SongTier.MID.value)
    return str(SongTier.HOT.value)


def _to_row(song: Song) -> CatalogRow:
    target = max(song.target_streams_per_day, 1)
    progress = round(min(song.current_streams_today / target, 1.0) * 100.0, 1)
    return CatalogRow(
        spotify_uri=song.spotify_uri,
        title=song.title,
        artist=song.artist_name,
        label=song.label_id or "—",
        tier=_display_tier(song),
        baseline=round(song.baseline_streams_per_day, 1),
        target=song.target_streams_per_day,
        today_count=song.current_streams_today,
        progress_pct=progress,
        is_active=song.is_active,
        flagged=song.spike_oct2025_flag,
        pilot_eligible=song.is_pilot_eligible,
    )


@st.cache_data(ttl=15, show_spinner=False)
def _load_targets_dataframe() -> pd.DataFrame:
    """Carga targets cacheado por 15s y los convierte a DataFrame."""
    state = get_state()
    songs = state.repos.list_target_songs()
    rows = [_to_row(s) for s in songs]
    return pd.DataFrame([asdict(row) for row in rows])


def render() -> None:
    state = get_state()
    st.title("Catalogo")

    df = _load_targets_dataframe()
    if df.empty:
        st.info("No hay canciones target en la base de datos.")
        return

    # ── KPI tiles ────────────────────────────────────────────────────────
    total = len(df)
    eligible = int(df["pilot_eligible"].sum())
    today_streams = int(df["today_count"].sum())
    flagged = int(df["flagged"].sum())
    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Total", f"{total}")
    col_b.metric("Eligibles piloto", f"{eligible}")
    col_c.metric("Streams hoy", f"{today_streams}")
    col_d.metric("FLAGGED", f"{flagged}")

    st.divider()

    # ── Filtros ──────────────────────────────────────────────────────────
    with st.expander("Filtros", expanded=True):
        artists_avail = sorted(df["artist"].unique().tolist())
        tiers_avail = sorted(df["tier"].unique().tolist())
        artist_sel = st.multiselect("Artista", artists_avail)
        tier_sel = st.multiselect("Tier", tiers_avail)
        only_eligible = st.checkbox("Solo elegibles para piloto", value=False)
        only_flagged = st.checkbox("Solo FLAGGED", value=False)
        title_q = st.text_input("Buscar por titulo", value="")

    filtered = df.copy()
    if artist_sel:
        filtered = filtered[filtered["artist"].isin(artist_sel)]
    if tier_sel:
        filtered = filtered[filtered["tier"].isin(tier_sel)]
    if only_eligible:
        filtered = filtered[filtered["pilot_eligible"]]
    if only_flagged:
        filtered = filtered[filtered["flagged"]]
    if title_q.strip():
        needle = title_q.strip().lower()
        filtered = filtered[filtered["title"].str.lower().str.contains(needle)]

    st.subheader(f"Canciones ({len(filtered)})")
    st.dataframe(
        filtered,
        use_container_width=True,
        hide_index=True,
        column_config={
            "progress_pct": st.column_config.ProgressColumn(
                "Progreso (%)", min_value=0, max_value=100, format="%.1f%%"
            ),
            "is_active": st.column_config.CheckboxColumn("Activa"),
            "flagged": st.column_config.CheckboxColumn("FLAGGED"),
            "pilot_eligible": st.column_config.CheckboxColumn("Piloto"),
        },
    )

    # ── Bulk actions ─────────────────────────────────────────────────────
    st.subheader("Acciones masivas")
    options = filtered["spotify_uri"].tolist()
    if not options:
        st.info("Filtra canciones para habilitar acciones masivas.")
    else:
        selected_uris = st.multiselect(
            "Selecciona canciones (URI) para aplicar la accion",
            options,
            help="Selecciona una o varias canciones del subset filtrado.",
        )
        action = st.selectbox(
            "Accion",
            (
                "Toggle is_active",
                "Cambiar tier",
                "Marcar protegido (HOT)",
                "Excluir del piloto (FLAGGED)",
            ),
        )
        new_tier_value: str | None = None
        if action == "Cambiar tier":
            new_tier_value = st.selectbox(
                "Nuevo tier",
                [t.value for t in SongTier],
                index=2,
            )
        if st.button("Aplicar", type="primary", disabled=not selected_uris):
            try:
                _apply_bulk_action(
                    state=state,
                    selected_uris=selected_uris,
                    action=action,
                    new_tier_value=new_tier_value,
                )
                st.success(f"Aplicada {action!r} a {len(selected_uris)} cancion(es).")
                st.cache_data.clear()
            except Exception as exc:
                st.error(f"Fallo aplicando accion: {exc}")

    st.divider()

    # ── Plotly charts ────────────────────────────────────────────────────
    chart_col_left, chart_col_right = st.columns(2)
    with chart_col_left:
        st.subheader("Distribucion por tier")
        tier_counts = df.groupby("tier", as_index=False).size().rename(columns={"size": "count"})
        fig_pie = px.pie(
            tier_counts,
            names="tier",
            values="count",
            hole=0.4,
            title="Catalogo por tier",
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with chart_col_right:
        st.subheader("Top 20 por capacidad restante")
        df_capacity = df.copy()
        df_capacity["remaining"] = (df_capacity["target"] - df_capacity["today_count"]).clip(
            lower=0
        )
        top20 = df_capacity.sort_values("remaining", ascending=False).head(20)
        fig_bar = px.bar(
            top20,
            x="title",
            y="remaining",
            color="artist",
            title="Capacidad restante hoy (target - today_count)",
        )
        fig_bar.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig_bar, use_container_width=True)


def _apply_bulk_action(
    *,
    state: DashboardState,
    selected_uris: list[str],
    action: str,
    new_tier_value: str | None,
) -> None:
    """Aplica la accion masiva sobre cada cancion seleccionada.

    Implementacion conservadora: una transaccion por cancion (mas faciles
    de auditar; el numero objetivo es <100 canciones por accion humana).
    """
    songs = state.repos.list_target_songs()
    by_uri = {s.spotify_uri: s for s in songs}

    for uri in selected_uris:
        song = by_uri.get(uri)
        if song is None:
            continue
        if action == "Toggle is_active":
            song.is_active = not song.is_active
        elif action == "Cambiar tier" and new_tier_value:
            song.tier = SongTier(new_tier_value)
        elif action == "Marcar protegido (HOT)":
            song.tier = SongTier.HOT
            song.is_active = False
        elif action == "Excluir del piloto (FLAGGED)":
            song.tier = SongTier.FLAGGED
            song.spike_oct2025_flag = True
        state.repos.update_song(song)


render()
