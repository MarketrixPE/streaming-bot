"""Pagina Monitors: alertas de distribuidores y estado del kill-switch.

Esta pagina actua como hub humano: refleja el estado del
``IPanicKillSwitch`` y permite reset manual con justificacion.

Las alertas reales vendran de los monitores asyncronos cuando se conecten
a un store persistente; mientras tanto, mostramos:
- Estado del kill-switch + ultimo audit log.
- Boton para activar panic con razon.
- Form de reset autorizado.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from streaming_bot.domain.ports.distributor_monitor import DistributorPlatform
from streaming_bot.presentation.dashboard.state import get_state


def _read_audit_tail(path: Path, lines: int = 20) -> list[str]:
    """Lee las ultimas N lineas del audit log (placeholder UI)."""
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return raw[-lines:]


def render() -> None:
    state = get_state()
    st.title("Monitores")

    kill_active = state.runner.run(state.kill_switch.is_active())
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Kill-switch", "ACTIVO" if kill_active else "OK")
    col_b.metric(
        "Marker",
        "presente" if state.settings.kill_switch_marker_path.exists() else "ausente",
    )
    col_c.metric(
        "Audit lines",
        f"{len(_read_audit_tail(state.settings.kill_switch_audit_path, lines=10000))}",
    )

    st.divider()

    if kill_active:
        st.error(
            "Kill-switch ACTIVO. El scheduler debe estar detenido. "
            "Resetear solo tras revision manual con auditor."
        )
        with st.form("reset_kill_switch"):
            authorized_by = st.text_input("Autorizado por")
            justification = st.text_area("Justificacion")
            submitted = st.form_submit_button("Reset kill-switch", type="primary")
            if submitted:
                if not authorized_by.strip() or not justification.strip():
                    st.warning("Autorizado y justificacion son obligatorios.")
                else:
                    try:
                        state.runner.run(
                            state.kill_switch.reset(
                                authorized_by=authorized_by.strip(),
                                justification=justification.strip(),
                            )
                        )
                        st.success("Kill-switch reseteado y registrado en audit log.")
                    except Exception as exc:
                        st.error(f"Reset fallo: {exc}")
    else:
        st.success(
            "Kill-switch OK. El scheduler puede operar mientras los monitores "
            "no detecten alertas criticas."
        )
        with st.form("activate_panic"):
            reason = st.text_input(
                "Razon para activar panic",
                placeholder="ej. anomalia en daily_streams (manual)",
            )
            submitted = st.form_submit_button("Activate panic", type="primary")
            if submitted:
                if not reason.strip():
                    st.warning("La razon es obligatoria para activar panic.")
                else:
                    try:
                        state.runner.run(state.kill_switch.trigger(reason=reason.strip()))
                        st.error("Kill-switch activado. Recarga la pagina.")
                    except Exception as exc:
                        st.error(f"Activacion fallo: {exc}")

    st.divider()

    st.subheader("Audit log (ultimas 20 entradas)")
    audit_lines = _read_audit_tail(state.settings.kill_switch_audit_path, lines=20)
    if not audit_lines:
        st.caption("Sin entradas todavia.")
    else:
        st.code("\n".join(audit_lines), language="json")

    st.divider()

    st.subheader("Estado por plataforma de distribucion")
    placeholder_msg = (
        "Las alertas reales se persisten cuando los monitores async tengan un "
        "store dedicado (otra epica). Mientras tanto, esta seccion muestra "
        "los puertos esperados y placeholders por plataforma."
    )
    st.caption(placeholder_msg)
    for platform in DistributorPlatform:
        with st.expander(f"{platform.value.upper()}", expanded=False):
            st.write("Sin alertas registradas (placeholder).")


render()
