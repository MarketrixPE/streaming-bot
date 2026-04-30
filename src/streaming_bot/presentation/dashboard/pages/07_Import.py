"""Pagina Import: subida de Excel/CSV multi-artista.

Flujo:
1. El operador sube archivo .xlsx o .csv.
2. Pandas parsea, mostramos preview (20 rows) + columnas detectadas.
3. Form para mapear artista (existente o nuevo) + label + distributor.
4. ``Run import`` invoca ``ImportCatalogService.import_excel(...)``.

EPIC 13 entregara el ``ImportCatalogService`` real. Aqui dejamos el
wiring listo: importamos via ``importlib`` dentro del handler para que
la pagina cargue aunque el servicio aun no exista.
"""

from __future__ import annotations

import importlib
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from streaming_bot.domain.label import DistributorType
from streaming_bot.presentation.dashboard.state import get_state


def _read_uploaded(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Detecta formato por extension y devuelve el DataFrame."""
    suffix = Path(filename).suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(BytesIO(file_bytes))
    if suffix == ".csv":
        return pd.read_csv(BytesIO(file_bytes))
    raise ValueError(f"Formato no soportado: {suffix}")


def _try_import_service() -> Any | None:
    """Intenta cargar ``ImportCatalogService`` (entregable de EPIC 13)."""
    try:
        module = importlib.import_module("streaming_bot.application.import_catalog")
    except ImportError:
        return None
    return getattr(module, "ImportCatalogService", None)


def render() -> None:
    get_state()  # Inicializa engine/runner via cache
    st.title("Import de catalogo")
    st.caption(
        "Sube un Excel/CSV multi-artista. Esta pagina mapea artista/label/"
        "distribuidor y delega al ``ImportCatalogService`` (EPIC 13)."
    )

    uploaded = st.file_uploader(
        "Archivo Excel o CSV",
        type=["xlsx", "xlsm", "xls", "csv"],
    )

    if uploaded is None:
        st.info("Arrastra un archivo aqui para empezar.")
        return

    try:
        file_bytes = uploaded.read()
        df_preview = _read_uploaded(file_bytes, uploaded.name)
    except Exception as exc:
        st.error(f"Error al parsear el archivo: {exc}")
        return

    st.success(
        f"Archivo `{uploaded.name}` cargado: {len(df_preview)} filas, "
        f"{len(df_preview.columns)} columnas."
    )

    st.subheader("Preview (primeras 20 filas)")
    st.dataframe(df_preview.head(20), use_container_width=True)

    st.subheader("Columnas detectadas")
    st.write(list(df_preview.columns))

    st.divider()

    st.subheader("Mapeo de artista, label y distribuidor")
    with st.form("import_form"):
        artist_mode = st.radio(
            "Artista",
            ("Existente", "Nuevo"),
            horizontal=True,
            help="Si seleccionas 'Existente', se asume que ya esta dado de alta.",
        )
        if artist_mode == "Existente":
            artist_value = st.text_input(
                "Nombre del artista existente",
                placeholder="ej. Tony Jaxx",
            )
        else:
            artist_value = st.text_input(
                "Nombre del nuevo artista",
                placeholder="ej. New Project",
            )

        label_mode = st.radio(
            "Label",
            ("Existente", "Nuevo"),
            horizontal=True,
        )
        if label_mode == "Existente":
            label_value = st.text_input(
                "Nombre del label existente",
                placeholder="ej. Worldwide Hits",
            )
        else:
            label_value = st.text_input(
                "Nombre del nuevo label",
                placeholder="ej. New Indie Sello",
            )

        distributor_value = st.selectbox(
            "Distribuidor",
            [d.value for d in DistributorType],
            index=0,
        )

        title_column = st.selectbox(
            "Columna del titulo",
            list(df_preview.columns),
            index=0,
        )

        submitted = st.form_submit_button("Run import", type="primary")

    if submitted:
        errors: list[str] = []
        if not artist_value.strip():
            errors.append("El nombre del artista es obligatorio.")
        if not label_value.strip():
            errors.append("El nombre del label es obligatorio.")
        if errors:
            for e in errors:
                st.warning(e)
            return

        service_cls = _try_import_service()
        if service_cls is None:
            st.warning(
                "``streaming_bot.application.import_catalog.ImportCatalogService`` "
                "aun no existe (EPIC 13). Wiring listo: cuando exista, este "
                "boton invocara ``service.import_excel(file_bytes, ...)``."
            )
            st.code(
                f"service.import_excel(\n"
                f"    file_bytes=...,\n"
                f"    filename={uploaded.name!r},\n"
                f"    artist_name={artist_value!r},\n"
                f"    artist_is_new={artist_mode == 'Nuevo'},\n"
                f"    label_name={label_value!r},\n"
                f"    label_is_new={label_mode == 'Nuevo'},\n"
                f"    distributor={distributor_value!r},\n"
                f"    title_column={title_column!r},\n"
                f")",
                language="python",
            )
            st.info(
                "Stub: import marcado como exito ficticio para validacion del UI. "
                "Reemplaza este branch cuando EPIC 13 entregue el servicio."
            )
            return

        try:
            state = get_state()
            service = service_cls(session_factory=state.session_factory)
            result = state.runner.run(
                service.import_excel(
                    file_bytes=file_bytes,
                    filename=uploaded.name,
                    artist_name=artist_value.strip(),
                    artist_is_new=(artist_mode == "Nuevo"),
                    label_name=label_value.strip(),
                    label_is_new=(label_mode == "Nuevo"),
                    distributor=distributor_value,
                    title_column=title_column,
                )
            )
        except Exception as exc:
            st.error(f"Import fallo: {exc}")
            return

        st.success(f"Import OK: {result}")


render()
