"""Builders de archivos sinteticos para tests del pipeline de import.

Genera xlsx/csv con datos minimos pero realistas (replica los quirks del
formato de aiCom: trailing whitespace, datetime.time como titulos, etc.).
"""

from __future__ import annotations

from datetime import time
from pathlib import Path

import pandas as pd

from streaming_bot.application.import_catalog.parsers import ParsedCatalogRow


def make_aicom_xlsx(path: Path, *, include_quirks: bool = True) -> None:
    """Crea un xlsx aiCom-like minimo con 2 canciones y datos en multiples meses.

    Args:
        path: Destino del archivo.
        include_quirks: Si True, replica trailing whitespace y datetime.time
            que aparecen en exports reales.
    """
    title_a: object = time(11, 11) if include_quirks else "11:11"
    rows = [
        # Song 1: 11:11 (datetime.time quirk) — Spotify dominante en GB
        _aicom_row(
            title_a,
            "QZMZ92544149",
            "young eiby (performer), Tony Jaxx (featuring)",
            "Worldwide Hits",
            "2026-01",
            1500,
            "GB",
            "Spotify",
        ),
        _aicom_row(
            title_a,
            "QZMZ92544149",
            "young eiby (performer), Tony Jaxx (featuring)",
            "Worldwide Hits",
            "2026-01",
            200,
            "PE",
            "YouTube",
        ),
        _aicom_row(
            title_a,
            "QZMZ92544149",
            "young eiby (performer), Tony Jaxx (featuring)",
            "Worldwide Hits",
            "2026-02",
            470,
            "GB",
            "Spotify Ad Supported",
        ),
        # Song 2: Salimos Pa La Calle — multi-mes
        _aicom_row(
            "Salimos Pa La Calle",
            "QZNJX2219848",
            "Tony Jaxx (performer), Jay Med (featuring)",
            "Worldwide Hits",
            "2025-11",
            100,
            "MX",
            "Spotify",
        ),
        _aicom_row(
            "Salimos Pa La Calle",
            "QZNJX2219848",
            "Tony Jaxx (performer), Jay Med (featuring)",
            "Worldwide Hits",
            "2025-12",
            250,
            "MX",
            "Spotify",
        ),
        _aicom_row(
            "Salimos Pa La Calle",
            "QZNJX2219848",
            "Tony Jaxx (performer), Jay Med (featuring)",
            "Worldwide Hits",
            "2026-01",
            800,
            "MX",
            "Spotify",
        ),
        # Sale Type Download (deberia ser filtrada)
        {
            **_aicom_row(
                "Salimos Pa La Calle",
                "QZNJX2219848",
                "Tony Jaxx (performer), Jay Med (featuring)",
                "Worldwide Hits",
                "2026-01",
                999,
                "MX",
                "Spotify",
            ),
            "Sales Type": "Download",
        },
    ]
    if include_quirks:
        for row in rows:
            row["ID"] = f"{row['ID']} "
            row["Transaction Month"] = f"{row['Transaction Month']} "
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sales")


def _aicom_row(
    title: object,
    isrc: str,
    artists: str,
    label: str,
    month: str,
    quantity: int,
    territory: str,
    store: str,
) -> dict[str, object]:
    return {
        "Source Account": label,
        "Title": title,
        "Album/Channel": title,
        "Artists": artists,
        "Label": label,
        "Product Type": "Track",
        "Parent ID": 700_000_000_000,
        "ID": isrc,
        "Sales Type": "Stream",
        "Transaction Month": month,
        "Accounted Date": f"{month}-28",
        "Quantity": quantity,
        "Territory": territory,
        "Store": store,
        "Currency": "USD",
        "Gross": 0.001 * quantity,
        "Net": 0.0007 * quantity,
    }


def make_distrokid_csv(path: Path) -> None:
    """Crea un CSV DistroKid-like minimo con 2 canciones."""
    rows = [
        _distrokid_row(
            "Sample Track", "USXYZ1234567", "Demo Artist", "Spotify", "2026-01", 5000, "US"
        ),
        _distrokid_row(
            "Sample Track", "USXYZ1234567", "Demo Artist", "Apple Music", "2026-01", 1200, "US"
        ),
        _distrokid_row(
            "Otra Cancion", "USXYZ1234999", "Otra Banda", "Spotify", "2026-01", 50, "MX"
        ),
    ]
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _distrokid_row(
    title: str,
    isrc: str,
    artist: str,
    store: str,
    month: str,
    quantity: int,
    country: str,
) -> dict[str, object]:
    return {
        "Reporting Date": f"{month}-28",
        "Sale Month": month,
        "Store": store,
        "Artist": artist,
        "Title": title,
        "ISRC": isrc,
        "UPC": "111222333444",
        "Quantity": quantity,
        "Country of Sale": country,
        "Earnings (USD)": 0.001 * quantity,
    }


def make_onerpm_csv(path: Path) -> None:
    """Crea un CSV OneRPM-like minimo."""
    rows = [
        {
            "Track Title": "Hit One",
            "Track ISRC": "BR1234567890",
            "Streams": 100,
            "Country": "BR",
            "Date": "2026-01",
            "Service": "Spotify",
        },
        {
            "Track Title": "Hit One",
            "Track ISRC": "BR1234567890",
            "Streams": 50,
            "Country": "BR",
            "Date": "2026-02",
            "Service": "Spotify",
        },
        {
            "Track Title": "Slow Burn",
            "Track ISRC": "BR1234567891",
            "Streams": 30,
            "Country": "BR",
            "Date": "2026-01",
            "Service": "YouTube",
        },
    ]
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def make_generic_csv(path: Path) -> None:
    """Crea un CSV pre-agregado tipo ``baseline_catalog_full.csv``."""
    rows = [
        {
            "Title": "PreAgg One",
            "ID": "AAAA00000001",
            "Artists": "Test Artist (performer)",
            "account": "test_label",
            "tier": "RISING",
            "avg_per_month": 5000.0,
            "total_lifetime": 50000,
            "last_3m": 15000,
            "months_active": 10,
            "flagged_oct": False,
            "spike_ratio": 1.5,
        },
        {
            "Title": "PreAgg Two",
            "ID": "AAAA00000002",
            "Artists": "Other Artist (performer), Feat Guy (featuring)",
            "account": "test_label",
            "tier": "MID",
            "avg_per_month": 2000.0,
            "total_lifetime": 16000,
            "last_3m": 6000,
            "months_active": 8,
            "flagged_oct": False,
            "spike_ratio": 1.1,
        },
    ]
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def make_flagged_csv(path: Path, *, isrcs: list[str] | None = None) -> None:
    """Crea un CSV de flagged Oct'25-style minimo."""
    isrcs = isrcs or ["QZMZ92544149"]
    rows = [
        {
            "Title": f"Track {i}",
            "ID": isrc,
            "Artists": "X",
            "account": "test",
            "spike_ratio": 5.0,
            "oct": 1000,
            "sep": 100,
            "nov": 200,
        }
        for i, isrc in enumerate(isrcs)
    ]
    pd.DataFrame(rows).to_csv(path, index=False)


def make_parsed_row(
    *,
    title: str = "Demo Song",
    artist_name: str = "Demo Artist",
    isrc: str | None = "USXYZ0000001",
    avg: float = 5000.0,
    total: int = 50_000,
    last_30d: int = 5000,
    spotify_total: int = 30_000,
    non_spotify_total: int = 20_000,
    spike_ratio: float = 0.0,
) -> ParsedCatalogRow:
    """Builder de ``ParsedCatalogRow`` para tests del classifier/service."""
    return ParsedCatalogRow(
        title=title,
        artist_name=artist_name,
        featured_artist_names=(),
        isrc=isrc,
        avg_streams_per_month=avg,
        total_streams=total,
        last_30d_streams=last_30d,
        spotify_streams_total=spotify_total,
        non_spotify_streams_total=non_spotify_total,
        spike_ratio=spike_ratio,
    )


__all__ = [
    "make_aicom_xlsx",
    "make_distrokid_csv",
    "make_flagged_csv",
    "make_generic_csv",
    "make_onerpm_csv",
    "make_parsed_row",
]
