"""Pagina Pilot: plan diario y controles de start/pause/panic."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from streaming_bot.presentation.dashboard.state import get_state


@st.cache_data(ttl=10, show_spinner=False)
def _load_pilot_plan() -> pd.DataFrame:
    state = get_state()
    eligible = state.repos.list_pilot_eligible(max_songs=120)
    rows: list[dict[str, object]] = []
    for s in eligible:
        target = max(s.target_streams_per_day, 1)
        progress = round(min(s.current_streams_today / target, 1.0) * 100.0, 1)
        rows.append(
            {
                "title": s.title,
                "artist": s.artist_name,
                "target": s.target_streams_per_day,
                "current": s.current_streams_today,
                "progress_pct": progress,
                "remaining": max(s.target_streams_per_day - s.current_streams_today, 0),
            }
        )
    return pd.DataFrame(rows)


def render() -> None:
    state = get_state()
    flags = state.flags_store.load()
    st.title("Piloto")

    df = _load_pilot_plan()

    total_target = int(df["target"].sum()) if not df.empty else 0
    total_current = int(df["current"].sum()) if not df.empty else 0
    overall_progress = round((total_current / total_target) * 100.0, 1) if total_target else 0.0

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Canciones piloto", f"{len(df)}")
    col_b.metric("Target diario", f"{total_target}")
    col_c.metric("Streams hoy", f"{total_current}")
    col_d.metric("Avance global", f"{overall_progress}%")

    st.divider()

    st.subheader("Controles")
    if flags.pilot_paused:
        st.warning(
            f"Piloto pausado por: **{flags.pilot_paused_reason or 'sin razon'}** "
            f"(at {flags.pilot_paused_at or 'unknown'})."
        )
    btn_start, btn_pause, btn_panic = st.columns(3)
    with btn_start:
        if st.button("Start pilot", type="primary", disabled=flags.pilot_paused):
            st.info(
                "Placeholder: el use-case StartPilot aun no esta cableado. "
                "Cuando EPIC 6/7 expongan ``StartPilotUseCase``, este boton "
                "lo invocara."
            )
    with btn_pause:
        if st.button("Pause pilot", disabled=flags.pilot_paused):
            reason = st.session_state.get("pause_reason", "manual op")
            state.flags_store.pause_pilot(reason)
            st.success("Piloto marcado como pausado.")
            st.cache_data.clear()
    with btn_panic:
        if st.button("Panic stop", type="secondary"):
            state.runner.run(state.kill_switch.trigger(reason="panic_from_dashboard"))
            state.flags_store.pause_pilot("panic")
            st.error("Kill-switch activado y piloto pausado.")
            st.cache_data.clear()

    if flags.pilot_paused and st.button("Reanudar piloto", type="secondary"):
        state.flags_store.resume_pilot()
        st.success("Pause levantada.")
        st.cache_data.clear()

    st.text_input(
        "Razon de pause (opcional)",
        key="pause_reason",
        help="Se persiste en data/dashboard_flags.json para auditoria.",
    )

    st.divider()

    st.subheader("Plan de hoy")
    if df.empty:
        st.info(
            "No hay canciones elegibles para piloto. Revisa Catalog para "
            "asegurar que haya canciones zombie/low/mid no FLAGGED."
        )
    else:
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "progress_pct": st.column_config.ProgressColumn(
                    "Progreso (%)", min_value=0, max_value=100, format="%.1f%%"
                ),
            },
        )

    st.divider()

    st.subheader("Progreso por hora (placeholder)")
    if df.empty:
        st.caption(
            "Cuando el scheduler de ramp-up este vivo, esta grafica mostrara "
            "streams_per_hour acumulados. Por ahora visualizamos el target "
            "distribuido linealmente entre 8h-22h."
        )
    else:
        hours = list(range(8, 22))
        records = []
        per_hour = max(total_target // len(hours), 1) if total_target else 0
        running = 0
        for h in hours:
            running += per_hour
            records.append({"hour": f"{h:02d}:00", "expected": running})
        chart = pd.DataFrame(records)
        fig = px.line(
            chart,
            x="hour",
            y="expected",
            markers=True,
            title="Curva esperada (placeholder lineal)",
        )
        st.plotly_chart(fig, use_container_width=True)


render()
