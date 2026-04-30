"""Tests de los parsers de distribuidor.

Cubre auto-deteccion, agregacion correcta, manejo de quirks (datetime.time,
trailing whitespace, Sales Type filtering) y errores en formatos invalidos.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from streaming_bot.application.import_catalog.parsers import (
    AiComParser,
    DistributorParserDetector,
    DistroKidParser,
    GenericCsvParser,
    OneRpmParser,
    ParsedCatalogRow,
)
from streaming_bot.domain.label import DistributorType
from streaming_bot.domain.value_objects import Country
from tests.fixtures.import_catalog.builders import (
    make_aicom_xlsx,
    make_distrokid_csv,
    make_generic_csv,
    make_onerpm_csv,
)


@pytest.mark.unit
def test_aicom_parser_handles_quirks_and_aggregates(tmp_path: Path) -> None:
    file = tmp_path / "aicom.xlsx"
    make_aicom_xlsx(file, include_quirks=True)

    parser = AiComParser()
    assert parser.can_parse(file)
    rows = list(parser.parse(file))

    assert len(rows) == 2

    by_isrc = {r.isrc: r for r in rows}
    song1 = by_isrc["QZMZ92544149"]
    assert song1.artist_name == "young eiby"
    assert song1.featured_artist_names == ("Tony Jaxx",)
    assert song1.label_name == "Worldwide Hits"
    assert song1.distributor == DistributorType.AICOM
    # Mes 2026-01 = 1500+200=1700, mes 2026-02 = 470 → 2 meses, total 2170
    assert song1.total_streams == 1700 + 470
    assert song1.months_active == 2
    assert song1.avg_streams_per_month == pytest.approx((1700 + 470) / 2)
    # Last 30d = ultimo mes (2026-02) = 470
    assert song1.last_30d_streams == 470
    # Spotify split: 1500 + 470 = 1970, no-Spotify (YouTube) = 200
    assert song1.spotify_streams_total == 1970
    assert song1.non_spotify_streams_total == 200
    assert song1.top_country == Country.GB

    song2 = by_isrc["QZNJX2219848"]
    # Sale Type 'Download' debe estar excluida
    assert song2.total_streams == 100 + 250 + 800
    assert song2.months_active == 3


@pytest.mark.unit
def test_aicom_parser_rejects_csv(tmp_path: Path) -> None:
    file = tmp_path / "x.csv"
    file.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    assert AiComParser().can_parse(file) is False


@pytest.mark.unit
def test_distrokid_parser_aggregates(tmp_path: Path) -> None:
    file = tmp_path / "distrokid.csv"
    make_distrokid_csv(file)

    parser = DistroKidParser()
    assert parser.can_parse(file)
    rows = list(parser.parse(file))

    by_isrc = {r.isrc: r for r in rows}
    big = by_isrc["USXYZ1234567"]
    assert big.artist_name == "Demo Artist"
    assert big.total_streams == 5000 + 1200
    assert big.spotify_streams_total == 5000
    assert big.non_spotify_streams_total == 1200
    assert big.top_country == Country.US


@pytest.mark.unit
def test_onerpm_parser_aggregates(tmp_path: Path) -> None:
    file = tmp_path / "onerpm.csv"
    make_onerpm_csv(file)

    parser = OneRpmParser()
    assert parser.can_parse(file)
    rows = list(parser.parse(file))
    assert len(rows) == 2
    by_isrc = {r.isrc: r for r in rows}
    hit = by_isrc["BR1234567890"]
    assert hit.total_streams == 150
    assert hit.months_active == 2
    assert hit.top_country == Country.BR


@pytest.mark.unit
def test_generic_csv_parses_pre_aggregated(tmp_path: Path) -> None:
    file = tmp_path / "generic.csv"
    make_generic_csv(file)
    parser = GenericCsvParser()
    assert parser.can_parse(file)
    rows = list(parser.parse(file))

    assert len(rows) == 2
    titles = sorted(r.title for r in rows)
    assert titles == ["PreAgg One", "PreAgg Two"]
    one = next(r for r in rows if r.title == "PreAgg One")
    assert one.avg_streams_per_month == 5000.0
    assert one.total_streams == 50000
    assert one.months_active == 10
    assert one.spike_ratio == 1.5


@pytest.mark.unit
def test_detector_picks_aicom_for_xlsx(tmp_path: Path) -> None:
    file = tmp_path / "aicom.xlsx"
    make_aicom_xlsx(file)
    parser = DistributorParserDetector.detect(file)
    assert isinstance(parser, AiComParser)


@pytest.mark.unit
def test_detector_picks_distrokid_csv(tmp_path: Path) -> None:
    file = tmp_path / "distrokid.csv"
    make_distrokid_csv(file)
    parser = DistributorParserDetector.detect(file)
    assert isinstance(parser, DistroKidParser)


@pytest.mark.unit
def test_detector_picks_onerpm_csv(tmp_path: Path) -> None:
    file = tmp_path / "onerpm.csv"
    make_onerpm_csv(file)
    parser = DistributorParserDetector.detect(file)
    assert isinstance(parser, OneRpmParser)


@pytest.mark.unit
def test_detector_picks_generic_csv(tmp_path: Path) -> None:
    file = tmp_path / "generic.csv"
    make_generic_csv(file)
    parser = DistributorParserDetector.detect(file)
    assert isinstance(parser, GenericCsvParser)


@pytest.mark.unit
def test_detector_raises_for_unknown_format(tmp_path: Path) -> None:
    file = tmp_path / "weird.txt"
    file.write_text("hola mundo\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no parser disponible"):
        DistributorParserDetector.detect(file)


@pytest.mark.unit
def test_parsed_row_stable_key_uses_isrc() -> None:
    row = ParsedCatalogRow(
        title="X",
        artist_name="Y",
        isrc="usxyz1234567",
    )
    assert row.stable_key == "isrc:USXYZ1234567"
    assert row.synthesize_spotify_uri() == "spotify:isrc:USXYZ1234567"


@pytest.mark.unit
def test_parsed_row_stable_key_falls_back_to_uri_or_title() -> None:
    row_with_uri = ParsedCatalogRow(
        title="X",
        artist_name="Y",
        spotify_uri="spotify:track:abc",
    )
    assert row_with_uri.stable_key == "spotify:track:abc"

    row_no_id = ParsedCatalogRow(title="Hello", artist_name="Bye")
    assert "title:hello" in row_no_id.stable_key
    assert "artist:bye" in row_no_id.stable_key
