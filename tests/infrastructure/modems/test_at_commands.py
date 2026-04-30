"""Tests de los parsers de respuestas AT."""

from __future__ import annotations

from streaming_bot.infrastructure.modems.at_commands import (
    extract_iccid,
    extract_imei,
    is_terminal_line,
    parse_cops,
    parse_csq,
)


class TestParseCsq:
    def test_typical_response(self) -> None:
        # rssi=20 -> -113 + 20*2 = -73 dBm
        assert parse_csq("\r\n+CSQ: 20,99\r\n\r\nOK\r\n") == -73

    def test_no_signal(self) -> None:
        # rssi=99 indica sin senal -> None.
        assert parse_csq("+CSQ: 99,99\r\n\r\nOK") is None

    def test_min_max_bounds(self) -> None:
        assert parse_csq("+CSQ: 0,99") == -113
        assert parse_csq("+CSQ: 31,99") == -51

    def test_invalid_response(self) -> None:
        assert parse_csq("garbage") is None
        # rssi fuera de rango -> None.
        assert parse_csq("+CSQ: 50,99") is None


class TestParseCops:
    def test_alpha_long_name(self) -> None:
        assert parse_cops('+COPS: 0,0,"Movistar PE",7\r\nOK') == "Movistar PE"

    def test_with_act_field(self) -> None:
        assert parse_cops('+COPS: 0,0,"Vodafone ES",2') == "Vodafone ES"

    def test_no_match(self) -> None:
        assert parse_cops("+COPS: 0\r\nOK") is None
        assert parse_cops("ERROR") is None


class TestExtractImei:
    def test_typical(self) -> None:
        assert extract_imei("AT+CGSN\r\n\r\n123456789012345\r\n\r\nOK\r\n") == "123456789012345"

    def test_returns_none_when_short(self) -> None:
        assert extract_imei("12345\nOK") is None


class TestExtractIccid:
    def test_with_prefix(self) -> None:
        assert extract_iccid("+CCID: 89510101234567890123\r\nOK") == "89510101234567890123"

    def test_without_prefix(self) -> None:
        assert extract_iccid("89510101234567890123\r\nOK") == "89510101234567890123"


class TestIsTerminalLine:
    def test_ok(self) -> None:
        assert is_terminal_line("OK")
        assert is_terminal_line("  OK  ")

    def test_error(self) -> None:
        assert is_terminal_line("ERROR")
        assert is_terminal_line("+CME ERROR: 100")
        assert is_terminal_line("+CMS ERROR: 500")

    def test_non_terminal(self) -> None:
        assert not is_terminal_line("+CSQ: 20,99")
        assert not is_terminal_line("")
