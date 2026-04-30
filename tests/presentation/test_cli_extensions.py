"""Tests para las extensiones del CLI (spotify, camouflage, playlist, account)."""

from __future__ import annotations

from typer.testing import CliRunner

from streaming_bot.presentation.cli import app

runner = CliRunner()


def test_spotify_help() -> None:
    """Verifica que el subcomando spotify este disponible."""
    result = runner.invoke(app, ["spotify", "--help"])
    assert result.exit_code == 0
    assert "spotify" in result.stdout.lower()


def test_camouflage_help() -> None:
    """Verifica que el subcomando camouflage este disponible."""
    result = runner.invoke(app, ["camouflage", "--help"])
    assert result.exit_code == 0
    assert "camouflage" in result.stdout.lower()


def test_playlist_help() -> None:
    """Verifica que el subcomando playlist este disponible."""
    result = runner.invoke(app, ["playlist", "--help"])
    assert result.exit_code == 0
    assert "playlist" in result.stdout.lower()


def test_account_help() -> None:
    """Verifica que el subcomando account este disponible."""
    result = runner.invoke(app, ["account", "--help"])
    assert result.exit_code == 0
    assert "account" in result.stdout.lower()
