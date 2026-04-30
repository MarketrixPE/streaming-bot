"""Pagina AccountFactory: creacion de cuentas nuevas."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streaming_bot.presentation.dashboard.state import get_state


@st.cache_data(ttl=20, show_spinner=False)
def _load_recent_accounts(limit: int = 20) -> pd.DataFrame:
    state = get_state()
    accounts = state.repos.list_accounts()
    # Sort by last_used_at, fallback to None if missing
    sorted_accounts = sorted(
        accounts,
        key=lambda a: a.last_used_at if a.last_used_at else None,  # type: ignore[return-value,arg-type]
        reverse=True,
    )
    recent = sorted_accounts[:limit]
    rows: list[dict[str, object]] = []
    for acc in recent:
        created_at_val = getattr(acc, "created_at", None)
        rows.append(
            {
                "id": acc.id[:8],
                "username": acc.username,
                "country": acc.country.value,
                "state": acc.status.state,
                "created_at": created_at_val.isoformat() if created_at_val else "-",
                "last_used_at": (acc.last_used_at.isoformat() if acc.last_used_at else "-"),
            }
        )
    return pd.DataFrame(rows)


def render() -> None:
    st.title("Account Factory")

    st.subheader("Crear cuenta nueva")
    st.warning(
        "Creacion de cuentas requiere SpotifyAccountCreator, MailTmEmailGateway, "
        "TwilioSmsGateway (o StubSmsGateway). Puede fallar si Spotify presenta captcha."
    )

    with st.form("create_account_form"):
        country_options = ["PE", "MX", "CL", "AR", "CO", "ES", "US"]
        country_sel = st.selectbox("Pais", country_options, index=0)
        use_stub_sms = st.checkbox("Usar stub SMS (sin Twilio)", value=True)
        submit = st.form_submit_button("Crear cuenta")

        if submit:
            st.info(
                f"Para crear cuenta en {country_sel} usa el CLI: "
                f"`streaming-bot account create --country {country_sel} "
                f"{'--use-stub-sms' if use_stub_sms else ''}`"
            )

    st.divider()

    st.subheader("Creaciones recientes")
    df = _load_recent_accounts(limit=20)
    if df.empty:
        st.info("No hay cuentas creadas.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    st.subheader("Warming pool")
    st.info(
        "Warming state requiere persistencia formal (TODO EPIC). "
        "Actualmente el warming se ejecuta en memoria dentro del AccountCreator. "
        "Para monitorear warming, revisar logs del orchestrator o usar: "
        "`streaming-bot account warming-status`."
    )


render()
