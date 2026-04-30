"""Parsers de catalogos por distribuidor.

Cada distribuidor tiene su propio formato de export (xlsx/csv). Los parsers
transforman ese formato heterogeneo a una representacion unica de dominio:
``ParsedCatalogRow``. Toda la logica especifica al formato del distribuidor
queda encapsulada aqui — el resto de la aplicacion consume rows uniformes.

Patrones aplicados:
- Strategy + Protocol (``IDistributorParser``) para extensibilidad sin
  modificar el codigo existente cuando aparezca un nuevo distribuidor.
- Factory con auto-deteccion (``DistributorParserDetector``) que selecciona
  el parser inspeccionando hojas/columnas del archivo.
- Sin I/O al dominio: la unica fuente de I/O es ``pandas`` leyendo el archivo.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

import pandas as pd

from streaming_bot.domain.label import DistributorType
from streaming_bot.domain.value_objects import Country

# ── Aliases publicos para mantener bajo el ratio cognitivo ────────────────────
SPOTIFY_STORE_KEYWORDS: tuple[str, ...] = ("spotify",)
"""Palabras clave en el campo ``Store`` que identifican plataforma Spotify."""

DEFAULT_STREAM_SALE_TYPE = "Stream"
"""Sales Type que cuenta como stream (vs Download)."""


# ── Modelos de dominio para esta capa (DTO de aplicacion) ─────────────────────


@dataclass(slots=True)
class ParsedCatalogRow:
    """Representacion neutral de una cancion despues del parseo.

    Es un DTO de la capa application. NO se persiste tal cual: el
    ``ImportCatalogService`` la traduce a entidades del dominio (``Song``,
    ``Artist``, ``Label``).

    Attributes:
        spotify_uri: URI de Spotify si esta disponible. La mayoria de los
            distribuidores NO lo exponen; en ese caso se sintetiza
            ``spotify:isrc:<ISRC>`` para tener una identidad estable y permitir
            idempotencia hasta que un humano mapee al URI real.
        title: Titulo de la cancion.
        artist_name: Nombre del artista principal (primer ``performer``).
        featured_artist_names: Nombres de artistas featuring.
        isrc: Codigo ISRC (clave natural mas confiable).
        release_date: Fecha de lanzamiento si esta disponible.
        distributor: Distribuidor que origino la fila.
        label_name: Nombre del label/cuenta distribuidora.
        avg_streams_per_month: Promedio mensual sobre meses con actividad.
        total_streams: Suma total de streams en el archivo.
        last_30d_streams: Streams del ultimo mes contabilizado.
        top_country: Pais con mayor volumen de streams.
        months_active: Numero de meses con al menos un stream.
        spike_ratio: Cociente del mes pico vs el promedio del resto. >1.0
            sugiere comportamiento anomalo.
        spotify_streams_total: Subset de ``total_streams`` originado en Spotify.
        non_spotify_streams_total: Subset originado en otros stores.
        raw: Diccionario de extras especificos al parser para debugging.
    """

    title: str
    artist_name: str
    featured_artist_names: tuple[str, ...] = ()
    spotify_uri: str | None = None
    isrc: str | None = None
    release_date: date | None = None
    distributor: DistributorType | None = None
    label_name: str | None = None
    avg_streams_per_month: float = 0.0
    total_streams: int = 0
    last_30d_streams: int = 0
    top_country: Country | None = None
    months_active: int = 0
    spike_ratio: float = 0.0
    spotify_streams_total: int = 0
    non_spotify_streams_total: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def stable_key(self) -> str:
        """Identidad estable: prioriza ISRC; cae a spotify_uri sintetizado.

        Garantiza que dos imports del mismo archivo produzcan la misma key
        para que el upsert sea idempotente.
        """
        if self.isrc:
            return f"isrc:{self.isrc.strip().upper()}"
        if self.spotify_uri:
            return self.spotify_uri
        return f"title:{self.title.strip().lower()}|artist:{self.artist_name.strip().lower()}"

    def synthesize_spotify_uri(self) -> str:
        """Devuelve un URI estable. Si no hay real, sintetiza uno via ISRC."""
        if self.spotify_uri:
            return self.spotify_uri
        if self.isrc:
            return f"spotify:isrc:{self.isrc.strip().upper()}"
        return f"spotify:title:{self.stable_key}"


# ── Protocolo del strategy ────────────────────────────────────────────────────


@runtime_checkable
class IDistributorParser(Protocol):
    """Protocolo para parsers de distribuidor (Strategy)."""

    distributor: DistributorType

    def can_parse(self, path: Path) -> bool:
        """Inspecciona el archivo y decide si este parser lo puede manejar."""
        ...

    def parse(self, path: Path) -> Iterable[ParsedCatalogRow]:
        """Parsea el archivo y produce ``ParsedCatalogRow`` por cancion."""
        ...


# ── Parsers concretos ─────────────────────────────────────────────────────────


class _BaseAggregatingParser:
    """Logica compartida para parsers basados en filas transaccionales.

    aiCom y DistroKid (y derivados) entregan archivos con una fila por
    transaccion (mes/territorio/store/cancion). Esta clase consolida esas
    filas en una agregacion por cancion (``ParsedCatalogRow``).
    """

    distributor: DistributorType = DistributorType.OTHER

    # Nombres canonicos esperados despues del normalizado.
    COL_TITLE = "title"
    COL_ARTISTS = "artists"
    COL_ID = "id"
    COL_LABEL = "label"
    COL_QUANTITY = "quantity"
    COL_TERRITORY = "territory"
    COL_STORE = "store"
    COL_MONTH = "transaction_month"
    COL_SALES_TYPE = "sales_type"

    def _aggregate(self, df: pd.DataFrame) -> Iterator[ParsedCatalogRow]:
        """Agrega filas transaccionales a un ``ParsedCatalogRow`` por cancion."""
        if df.empty:
            return

        df = self._normalize_columns(df)
        df = self._coerce_types(df)

        if self.COL_SALES_TYPE in df.columns:
            df = df[
                df[self.COL_SALES_TYPE].fillna("").str.casefold()
                == DEFAULT_STREAM_SALE_TYPE.casefold()
            ]
            if df.empty:
                return

        group_key = self.COL_ID if self.COL_ID in df.columns else self.COL_TITLE
        for _, group in df.groupby(group_key, sort=False):
            row = self._build_row_from_group(group)
            if row is not None:
                yield row

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normaliza nombres de columnas a snake_case."""
        rename: dict[str, str] = {}
        for col in df.columns:
            normalized = _normalize_header(str(col))
            rename[col] = normalized
        return df.rename(columns=rename)

    def _coerce_types(self, df: pd.DataFrame) -> pd.DataFrame:
        """Limpia tipos: trim strings, coerce numerics."""
        for col in (
            self.COL_ID,
            self.COL_TITLE,
            self.COL_ARTISTS,
            self.COL_LABEL,
            self.COL_TERRITORY,
            self.COL_STORE,
            self.COL_MONTH,
            self.COL_SALES_TYPE,
        ):
            if col in df.columns:
                df[col] = df[col].apply(_to_clean_str)
        if self.COL_QUANTITY in df.columns:
            df[self.COL_QUANTITY] = (
                pd.to_numeric(
                    df[self.COL_QUANTITY],
                    errors="coerce",
                )
                .fillna(0)
                .astype(int)
            )
        return df

    def _build_row_from_group(self, group: pd.DataFrame) -> ParsedCatalogRow | None:
        """Construye un ``ParsedCatalogRow`` a partir de filas de una cancion."""
        title = _first_non_empty(group, self.COL_TITLE) or "Untitled"
        artists_raw = _first_non_empty(group, self.COL_ARTISTS) or ""
        primary, featured = _parse_artists_field(artists_raw)
        if not primary:
            primary = "Unknown Artist"
        isrc = _first_non_empty(group, self.COL_ID)
        label = _first_non_empty(group, self.COL_LABEL)

        quantities = (
            group[self.COL_QUANTITY]
            if self.COL_QUANTITY in group.columns
            else pd.Series([0] * len(group))
        )
        total_streams = int(quantities.sum())

        # Aggregate by month
        per_month: dict[str, int] = defaultdict(int)
        if self.COL_MONTH in group.columns:
            for month, qty in zip(
                group[self.COL_MONTH],
                quantities,
                strict=False,
            ):
                key = _to_clean_str(month) or ""
                if key:
                    per_month[key] += int(qty)
        months_active = sum(1 for v in per_month.values() if v > 0)
        avg_streams_per_month = total_streams / months_active if months_active else 0.0
        last_30d = _last_month_quantity(per_month)

        # Top country
        per_country: dict[str, int] = defaultdict(int)
        if self.COL_TERRITORY in group.columns:
            for territory, qty in zip(
                group[self.COL_TERRITORY],
                quantities,
                strict=False,
            ):
                key = (_to_clean_str(territory) or "").upper()
                if key:
                    per_country[key] += int(qty)
        top_country = _resolve_top_country(per_country)

        # Spotify split
        spotify_total = 0
        non_spotify_total = 0
        if self.COL_STORE in group.columns:
            for store, qty in zip(group[self.COL_STORE], quantities, strict=False):
                store_str = (_to_clean_str(store) or "").casefold()
                if any(k in store_str for k in SPOTIFY_STORE_KEYWORDS):
                    spotify_total += int(qty)
                else:
                    non_spotify_total += int(qty)
        else:
            non_spotify_total = total_streams

        spike_ratio = _compute_spike_ratio(per_month)

        return ParsedCatalogRow(
            title=title,
            artist_name=primary,
            featured_artist_names=featured,
            isrc=isrc,
            label_name=label,
            distributor=self.distributor,
            avg_streams_per_month=avg_streams_per_month,
            total_streams=total_streams,
            last_30d_streams=last_30d,
            top_country=top_country,
            months_active=months_active,
            spike_ratio=spike_ratio,
            spotify_streams_total=spotify_total,
            non_spotify_streams_total=non_spotify_total,
            raw={"per_month": dict(per_month), "per_country": dict(per_country)},
        )


class AiComParser(_BaseAggregatingParser):
    """Parser para exports de aiCom (.xlsx con hoja ``Sales``).

    Formato observado (Apr 2026):
    - Hoja ``Sales`` con columnas: Source Account, Title, Album/Channel,
      Artists, Label, Product Type, Parent ID, ID, Sales Type, Transaction
      Month, Accounted Date, Quantity, Territory, Store, Currency, Gross, Net.
    - Quirks: trailing whitespace en ``ID``, ``Transaction Month``; titulos que
      como ``"11:11"`` los parsea openpyxl como ``datetime.time``.
    """

    distributor: DistributorType = DistributorType.AICOM
    SHEET_NAME: ClassVar[str] = "Sales"

    def can_parse(self, path: Path) -> bool:
        if path.suffix.lower() not in {".xlsx", ".xls", ".xlsm"}:
            return False
        try:
            sheets = pd.read_excel(path, sheet_name=None, nrows=0)
        except (OSError, ValueError):
            return False
        if self.SHEET_NAME not in sheets:
            return False
        cols = {_normalize_header(c) for c in sheets[self.SHEET_NAME].columns}
        return cols >= {"source_account", "title", "artists", "id", "quantity"}

    def parse(self, path: Path) -> Iterable[ParsedCatalogRow]:
        df = pd.read_excel(path, sheet_name=self.SHEET_NAME)
        yield from self._aggregate(df)


class DistroKidParser(_BaseAggregatingParser):
    """Parser para exports nativos de DistroKid (CSV/TSV).

    DistroKid expone columnas tipo: ``Reporting Date``, ``Sale Month``,
    ``Store``, ``Artist``, ``Title``, ``ISRC``, ``UPC``, ``Quantity``,
    ``Country of Sale``, ``Earnings (USD)``.
    """

    distributor: DistributorType = DistributorType.DISTROKID

    REQUIRED_COLS: ClassVar[set[str]] = {"sale_month", "isrc", "quantity"}

    def can_parse(self, path: Path) -> bool:
        if path.suffix.lower() not in {".csv", ".tsv", ".txt"}:
            return False
        try:
            df = pd.read_csv(path, nrows=0, sep=None, engine="python")
        except (OSError, ValueError):
            return False
        cols = {_normalize_header(c) for c in df.columns}
        return cols >= self.REQUIRED_COLS

    def parse(self, path: Path) -> Iterable[ParsedCatalogRow]:
        df = pd.read_csv(path, sep=None, engine="python")
        df = df.rename(columns=_distrokid_column_map(df.columns))
        yield from self._aggregate(df)


class OneRpmParser(_BaseAggregatingParser):
    """Parser para exports de OneRPM (CSV).

    OneRPM expone columnas tipo: ``Track Title``, ``Track ISRC``, ``Streams``,
    ``Country``, ``Date``, ``Service``.
    """

    distributor: DistributorType = DistributorType.ONERPM

    REQUIRED_COLS: ClassVar[set[str]] = {"track_isrc", "streams", "service"}

    def can_parse(self, path: Path) -> bool:
        if path.suffix.lower() not in {".csv", ".tsv", ".txt"}:
            return False
        try:
            df = pd.read_csv(path, nrows=0, sep=None, engine="python")
        except (OSError, ValueError):
            return False
        cols = {_normalize_header(c) for c in df.columns}
        return cols >= self.REQUIRED_COLS

    def parse(self, path: Path) -> Iterable[ParsedCatalogRow]:
        df = pd.read_csv(path, sep=None, engine="python")
        df = df.rename(columns=_onerpm_column_map(df.columns))
        yield from self._aggregate(df)


class GenericCsvParser:
    """Parser para CSVs ya pre-agregados (formato ``baseline_catalog_full``).

    Espera columnas: ``Title``, ``ID`` (ISRC), ``Artists``, ``account``,
    ``avg_per_month``, ``total_lifetime``, ``last_3m``, ``months_active``,
    ``spike_ratio`` (y opcionalmente ``flagged_oct``, ``tier``).
    """

    distributor: DistributorType = DistributorType.OTHER

    REQUIRED_COLS: ClassVar[set[str]] = {"title", "id", "artists"}

    def can_parse(self, path: Path) -> bool:
        if path.suffix.lower() not in {".csv", ".tsv", ".txt"}:
            return False
        try:
            df = pd.read_csv(path, nrows=0, sep=None, engine="python")
        except (OSError, ValueError):
            return False
        cols = {_normalize_header(c) for c in df.columns}
        if not cols >= self.REQUIRED_COLS:
            return False
        # Distinguir de DistroKid/OneRPM: si tiene su columna firma, no es generic
        return not ({"sale_month", "track_isrc", "streams", "service"} & cols)

    def parse(self, path: Path) -> Iterable[ParsedCatalogRow]:
        df = pd.read_csv(path, sep=None, engine="python")
        df = df.rename(columns={c: _normalize_header(str(c)) for c in df.columns})
        for _, raw_row in df.iterrows():
            row_dict: dict[str, Any] = {str(k): v for k, v in raw_row.to_dict().items()}
            yield self._row_from_pre_aggregated(row_dict)

    def _row_from_pre_aggregated(self, data: dict[str, Any]) -> ParsedCatalogRow:
        """Construye una row a partir de un CSV ya agregado por cancion."""
        title = _to_clean_str(data.get("title")) or "Untitled"
        artists_raw = _to_clean_str(data.get("artists")) or ""
        primary, featured = _parse_artists_field(artists_raw)
        if not primary:
            primary = "Unknown Artist"
        isrc = _to_clean_str(data.get("id"))
        label = _to_clean_str(data.get("account"))
        avg = _safe_float(data.get("avg_per_month"))
        total = int(_safe_float(data.get("total_lifetime")))
        last_3m = int(_safe_float(data.get("last_3m")))
        months_active = int(_safe_float(data.get("months_active")))
        spike_ratio = _safe_float(data.get("spike_ratio"))
        return ParsedCatalogRow(
            title=title,
            artist_name=primary,
            featured_artist_names=featured,
            isrc=isrc,
            label_name=label,
            distributor=self.distributor,
            avg_streams_per_month=avg,
            total_streams=total,
            last_30d_streams=last_3m // 3 if last_3m else 0,
            top_country=None,
            months_active=months_active,
            spike_ratio=spike_ratio,
            spotify_streams_total=0,
            non_spotify_streams_total=total,
            raw=dict(data),
        )


# ── Factory con auto-deteccion ───────────────────────────────────────────────


class DistributorParserDetector:
    """Selecciona el parser adecuado inspeccionando el archivo.

    El orden de evaluacion es importante: parsers mas especificos primero
    para evitar falsos positivos del ``GenericCsvParser``.
    """

    _PARSERS: ClassVar[tuple[IDistributorParser, ...]] = (
        AiComParser(),
        DistroKidParser(),
        OneRpmParser(),
        GenericCsvParser(),
    )

    @classmethod
    def detect(cls, path: Path) -> IDistributorParser:
        """Devuelve el parser adecuado para ``path``.

        Raises:
            ValueError: si ningun parser registrado puede manejar el archivo.
        """
        for parser in cls._PARSERS:
            if parser.can_parse(path):
                return parser
        msg = f"no parser disponible para el archivo {path}"
        raise ValueError(msg)

    @classmethod
    def detect_or_default(
        cls,
        path: Path,
        *,
        fallback: IDistributorParser | None = None,
    ) -> IDistributorParser:
        """Como ``detect`` pero retorna ``fallback`` en vez de lanzar."""
        try:
            return cls.detect(path)
        except ValueError:
            if fallback is not None:
                return fallback
            raise


# ── Helpers privados (puros, sin I/O) ─────────────────────────────────────────


_HEADER_RE = re.compile(r"[^a-z0-9]+")


def _normalize_header(header: str) -> str:
    """Convierte ``"Sale Month"`` -> ``"sale_month"``; idempotente."""
    h = header.strip().casefold()
    h = _HEADER_RE.sub("_", h)
    return h.strip("_")


def _to_clean_str(value: Any) -> str | None:
    """Castea a str y limpia. Devuelve ``None`` para vacios/NaN."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "nat"}:
        return None
    return text


def _safe_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(f) else f


def _first_non_empty(df: pd.DataFrame, column: str) -> str | None:
    """Devuelve el primer valor no vacio de la columna en el DataFrame."""
    if column not in df.columns:
        return None
    for value in df[column]:
        clean = _to_clean_str(value)
        if clean:
            return clean
    return None


def _parse_artists_field(raw: str) -> tuple[str, tuple[str, ...]]:
    """Parsea el campo ``Artists`` de aiCom: ``"Name (role), Name (role)..."``.

    Devuelve ``(primario, featured...)``. El primario es el primer
    ``performer``; si no hay performer, el primer item.
    """
    if not raw:
        return "", ()

    primary: str | None = None
    featured: list[str] = []
    seen: set[str] = set()
    fallback: str | None = None

    for chunk in (c.strip() for c in raw.split(",")):
        if not chunk:
            continue
        name, role = _split_name_role(chunk)
        if not name or name in seen:
            continue
        seen.add(name)
        if fallback is None:
            fallback = name
        if role == "performer" and primary is None:
            primary = name
        elif role == "featuring":
            featured.append(name)

    return (primary or fallback or "", tuple(featured))


_NAME_ROLE_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<role>[^)]+)\)\s*$")


def _split_name_role(chunk: str) -> tuple[str, str]:
    """Extrae ``(name, role)`` de ``"Name (role)"``. Si falla, role=''."""
    match = _NAME_ROLE_RE.match(chunk)
    if not match:
        return chunk.strip(), ""
    return match.group("name").strip(), match.group("role").strip().casefold()


def _last_month_quantity(per_month: dict[str, int]) -> int:
    """Devuelve la cantidad del mes mas reciente (orden lexicografico YYYY-MM)."""
    if not per_month:
        return 0
    sorted_keys = sorted(per_month.keys())
    return per_month[sorted_keys[-1]]


def _compute_spike_ratio(per_month: dict[str, int]) -> float:
    """Cociente entre el mes pico y el promedio del resto.

    Devuelve ``0.0`` si hay <2 meses con datos. Mide cuanto se sale del patron
    el mes anomalo. Un spike sano de boost ronda 4x-8x.
    """
    months = sorted(per_month.items())
    quantities = [q for _, q in months if q > 0]
    if len(quantities) < 2:
        return 0.0
    peak = max(quantities)
    rest = [q for q in quantities if q != peak]
    if not rest:
        return 0.0
    avg_rest = sum(rest) / len(rest)
    if avg_rest <= 0:
        return 0.0
    return peak / avg_rest


def _resolve_top_country(per_country: dict[str, int]) -> Country | None:
    """Devuelve el ``Country`` con mas streams; ``None`` si no esta soportado."""
    if not per_country:
        return None
    top_code, _ = max(per_country.items(), key=lambda kv: kv[1])
    try:
        return Country(top_code)
    except ValueError:
        return None


def _distrokid_column_map(columns: Iterable[str]) -> dict[str, str]:
    """Renombrado canonico de columnas DistroKid -> internas."""
    mapping = {
        "sale_month": "transaction_month",
        "isrc": "id",
        "country_of_sale": "territory",
        "country": "territory",
        "store": "store",
        "title": "title",
        "song_title": "title",
        "artist": "artists",
        "quantity": "quantity",
    }
    out: dict[str, str] = {}
    for col in columns:
        norm = _normalize_header(str(col))
        if norm in mapping:
            out[col] = mapping[norm]
    return out


def _onerpm_column_map(columns: Iterable[str]) -> dict[str, str]:
    """Renombrado canonico de columnas OneRPM -> internas."""
    mapping = {
        "track_title": "title",
        "track_isrc": "id",
        "isrc": "id",
        "streams": "quantity",
        "country": "territory",
        "service": "store",
        "date": "transaction_month",
        "month": "transaction_month",
        "artist": "artists",
    }
    out: dict[str, str] = {}
    for col in columns:
        norm = _normalize_header(str(col))
        if norm in mapping:
            out[col] = mapping[norm]
    return out


__all__ = [
    "AiComParser",
    "DistributorParserDetector",
    "DistroKidParser",
    "GenericCsvParser",
    "IDistributorParser",
    "OneRpmParser",
    "ParsedCatalogRow",
]
