"""Pagina Sessions: sesiones recientes con drill-down a behaviors."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streaming_bot.presentation.dashboard.state import get_state


@st.cache_data(ttl=10, show_spinner=False)
def _load_sessions(limit: int) -> pd.DataFrame:
    state = get_state()
    sessions = state.repos.list_recent_sessions(limit=limit)
    rows: list[dict[str, object]] = []
    for s in sessions:
        outcome = "counted" if s.completed_normally else "failed"
        if s.error_class:
            outcome = f"failed:{s.error_class}"
        rows.append(
            {
                "session_id": s.session_id,
                "account_id": s.account_id,
                "started_at": s.started_at.isoformat(),
                "ended_at": s.ended_at.isoformat() if s.ended_at else "",
                "duration_s": s.duration_seconds(),
                "target_streams": s.target_streams_attempted,
                "camouflage_streams": s.camouflage_streams_attempted,
                "behaviors_count": len(s.behavior_events),
                "outcome": outcome,
            }
        )
    return pd.DataFrame(rows)


def render() -> None:
    state = get_state()
    st.title("Sesiones")

    limit = st.slider("Mostrar ultimas N sesiones", min_value=10, max_value=500, value=100)
    df = _load_sessions(limit)
    if df.empty:
        st.info("Sin sesiones registradas todavia.")
        return

    total = len(df)
    failed = int(df["outcome"].str.startswith("failed").sum())
    avg_duration = round(float(df["duration_s"].mean()), 1)
    avg_streams = round(float(df["target_streams"].mean()), 2)

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Sesiones", f"{total}")
    col_b.metric("Fallidas", f"{failed}")
    col_c.metric("Duracion media (s)", f"{avg_duration}")
    col_d.metric("Streams media", f"{avg_streams}")

    st.divider()

    st.subheader("Listado")
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    st.subheader("Drill-down de behaviors")
    options = df["session_id"].tolist()
    sid = st.selectbox(
        "Selecciona una sesion para ver sus behaviors",
        options,
        index=0 if options else None,
    )
    if sid:
        record = state.repos.get_session(sid)
        if record is None:
            st.warning("Sesion no encontrada (posible inconsistencia).")
        else:
            event_rows = [
                {
                    "event_id": e.event_id,
                    "type": e.type.value,
                    "occurred_at": e.occurred_at.isoformat(),
                    "target_uri": e.target_uri or "",
                    "duration_ms": e.duration_ms,
                }
                for e in record.behavior_events
            ]
            st.write(
                f"**{len(event_rows)} eventos** | "
                f"{record.target_streams_attempted} target / "
                f"{record.camouflage_streams_attempted} camuflaje"
            )
            if event_rows:
                st.dataframe(
                    pd.DataFrame(event_rows),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("Sin eventos registrados.")


render()
