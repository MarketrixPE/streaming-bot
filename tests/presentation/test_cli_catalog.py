"""Tests del CLI extendido (catalog/artist/label/pilot/panic).

Usa typer.testing.CliRunner contra el ``app`` real, redirigiendo el
container a un directorio temporal para no contaminar ``./data``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from streaming_bot.presentation import cli as cli_module
from tests.fixtures.import_catalog.builders import make_aicom_xlsx


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_catalog_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    """Redirige el container del CLI a un directorio temporal."""
    catalog_dir = tmp_path / "catalog"
    flagged_path = tmp_path / "flagged.csv"
    flagged_path.write_text("Title,ID\n", encoding="utf-8")
    kill_switch_path = tmp_path / ".kill_switch"

    monkeypatch.setattr(cli_module, "DEFAULT_CATALOG_DIR", catalog_dir)
    monkeypatch.setattr(cli_module, "DEFAULT_FLAGGED_PATH", flagged_path)
    monkeypatch.setattr(cli_module, "DEFAULT_KILL_SWITCH_PATH", kill_switch_path)
    yield catalog_dir


def test_catalog_import_dry_run(
    runner: CliRunner,
    isolated_catalog_dir: Path,
    tmp_path: Path,
) -> None:
    file = tmp_path / "aicom.xlsx"
    make_aicom_xlsx(file)
    result = runner.invoke(
        cli_module.app,
        ["catalog", "import", str(file), "--distributor", "aicom", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "rows_seen" in result.output
    # No deberia haber persistencia (dry run)
    assert not (isolated_catalog_dir / "songs.json").exists()


def test_catalog_import_persists_then_stats_lists(
    runner: CliRunner,
    isolated_catalog_dir: Path,
    tmp_path: Path,
) -> None:
    file = tmp_path / "aicom.xlsx"
    make_aicom_xlsx(file)
    imp = runner.invoke(
        cli_module.app,
        ["catalog", "import", str(file), "--distributor", "aicom"],
    )
    assert imp.exit_code == 0, imp.output
    stats = runner.invoke(cli_module.app, ["catalog", "stats"])
    assert stats.exit_code == 0
    assert "Distribucion" in stats.output

    listing = runner.invoke(cli_module.app, ["catalog", "list"])
    assert listing.exit_code == 0
    assert "Catalogo" in listing.output


def test_artist_add_and_list(runner: CliRunner, isolated_catalog_dir: Path) -> None:
    add = runner.invoke(
        cli_module.app,
        ["artist", "add", "--name", "Lastrid"],
    )
    assert add.exit_code == 0, add.output
    assert "Artist OK" in add.output

    listing = runner.invoke(cli_module.app, ["artist", "list"])
    assert listing.exit_code == 0
    assert "Lastrid" in listing.output


def test_artist_pause_and_archive(
    runner: CliRunner,
    isolated_catalog_dir: Path,
) -> None:
    add = runner.invoke(
        cli_module.app,
        ["artist", "add", "--name", "TempArtist"],
    )
    artist_id = _extract_artist_id_from_output(add.output)

    pause = runner.invoke(
        cli_module.app,
        ["artist", "pause", artist_id, "--reason", "spike_detected"],
    )
    assert pause.exit_code == 0, pause.output
    assert "pausado" in pause.output

    archive = runner.invoke(cli_module.app, ["artist", "archive", artist_id])
    assert archive.exit_code == 0


def test_artist_pause_unknown_id_returns_error(
    runner: CliRunner,
    isolated_catalog_dir: Path,
) -> None:
    result = runner.invoke(
        cli_module.app,
        ["artist", "pause", "ghost-id"],
    )
    assert result.exit_code == 1


def test_label_add_and_list(runner: CliRunner, isolated_catalog_dir: Path) -> None:
    add = runner.invoke(
        cli_module.app,
        ["label", "add", "--name", "Worldwide Hits", "--distributor", "aicom"],
    )
    assert add.exit_code == 0, add.output

    listing = runner.invoke(cli_module.app, ["label", "list"])
    assert listing.exit_code == 0
    assert "Worldwide Hits" in listing.output


def test_pilot_status_runs_empty(
    runner: CliRunner,
    isolated_catalog_dir: Path,
) -> None:
    result = runner.invoke(cli_module.app, ["pilot", "status"])
    assert result.exit_code == 0
    assert "Pilot eligible hoy" in result.output


def test_panic_stop_and_clear_cycle(
    runner: CliRunner,
    isolated_catalog_dir: Path,
) -> None:
    stop = runner.invoke(
        cli_module.app,
        ["panic", "stop", "--reason", "test_kill"],
    )
    assert stop.exit_code == 0, stop.output
    assert cli_module.DEFAULT_KILL_SWITCH_PATH.exists()

    clear = runner.invoke(
        cli_module.app,
        ["panic", "clear", "--by", "ops", "--justification", "false_alarm"],
    )
    assert clear.exit_code == 0
    assert not cli_module.DEFAULT_KILL_SWITCH_PATH.exists()


def _extract_artist_id_from_output(output: str) -> str:
    """Saca el ``id=...`` del output de ``artist add``."""
    for token in output.split():
        if token.startswith("id="):
            return token.removeprefix("id=")
    raise AssertionError(f"no se encontro id en output: {output}")
