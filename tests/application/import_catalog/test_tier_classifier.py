"""Tests del TierClassifier: cubre cada bracket + spike + flagged."""

from __future__ import annotations

from pathlib import Path

import pytest

from streaming_bot.application.import_catalog.tier_classifier import (
    TierClassifier,
    load_flagged_oct2025,
)
from streaming_bot.domain.song import SongTier
from tests.fixtures.import_catalog.builders import make_flagged_csv, make_parsed_row


@pytest.mark.unit
@pytest.mark.parametrize(
    ("avg", "expected"),
    [
        (200_000.0, SongTier.HOT),
        (100_000.0, SongTier.HOT),
        (50_000.0, SongTier.RISING),
        (10_000.0, SongTier.RISING),
        (5_000.0, SongTier.MID),
        (1_000.0, SongTier.MID),
        (500.0, SongTier.LOW),
        (100.0, SongTier.LOW),
    ],
)
def test_classify_brackets(avg: float, expected: SongTier) -> None:
    classifier = TierClassifier()
    row = make_parsed_row(avg=avg, total=int(avg * 10))
    assert classifier.classify(row) == expected


@pytest.mark.unit
def test_classify_dead_when_no_streams() -> None:
    classifier = TierClassifier()
    row = make_parsed_row(avg=0.0, total=0, spotify_total=0, non_spotify_total=0)
    assert classifier.classify(row) == SongTier.DEAD


@pytest.mark.unit
def test_classify_zombie_when_low_spotify_high_social() -> None:
    classifier = TierClassifier()
    # avg <100 (debajo de LOW) pero con social total alto -> ZOMBIE
    row = make_parsed_row(
        avg=50.0,
        total=500,
        spotify_total=10,
        non_spotify_total=2000,
    )
    assert classifier.classify(row) == SongTier.ZOMBIE


@pytest.mark.unit
def test_classify_dead_when_spotify_low_no_social() -> None:
    classifier = TierClassifier()
    row = make_parsed_row(
        avg=0.0,
        total=0,
        spotify_total=0,
        non_spotify_total=0,
    )
    assert classifier.classify(row) == SongTier.DEAD


@pytest.mark.unit
def test_detect_spike_returns_true_above_threshold() -> None:
    classifier = TierClassifier()
    row = make_parsed_row()
    history = [100.0, 120.0, 150.0, 130.0, 1000.0]
    flagged, reason = classifier.detect_spike(row, history)
    assert flagged is True
    assert "spike_detected" in reason


@pytest.mark.unit
def test_detect_spike_uses_spike_ratio_when_history_clean() -> None:
    classifier = TierClassifier()
    row = make_parsed_row(spike_ratio=5.0)  # 5x supera threshold (3.0)
    flagged, reason = classifier.detect_spike(row, history=[100.0, 110.0, 105.0])
    assert flagged is True
    assert "spike_ratio_anomalo" in reason


@pytest.mark.unit
def test_detect_spike_returns_false_with_short_history() -> None:
    classifier = TierClassifier()
    row = make_parsed_row()
    flagged, reason = classifier.detect_spike(row, history=[100.0])
    assert flagged is False
    assert reason == ""


@pytest.mark.unit
def test_detect_spike_handles_zero_baseline() -> None:
    classifier = TierClassifier()
    row = make_parsed_row()
    flagged, _ = classifier.detect_spike(row, history=[0.0, 0.0, 100.0])
    assert flagged is False


@pytest.mark.unit
def test_is_flagged_oct2025_matches_set() -> None:
    flagged_set = {"USXYZ1234567", "SPOTIFY:TRACK:ABC"}
    assert TierClassifier.is_flagged_oct2025("USXYZ1234567", flagged_set)
    assert TierClassifier.is_flagged_oct2025("usxyz1234567", flagged_set)
    assert TierClassifier.is_flagged_oct2025("spotify:track:abc", flagged_set)
    assert not TierClassifier.is_flagged_oct2025("UNKNOWN", flagged_set)
    assert not TierClassifier.is_flagged_oct2025("", flagged_set)


@pytest.mark.unit
def test_load_flagged_oct2025_reads_csv(tmp_path: Path) -> None:
    file = tmp_path / "flagged.csv"
    make_flagged_csv(file, isrcs=["USAAA0000001", "USAAA0000002"])
    flagged = load_flagged_oct2025(file)
    assert "USAAA0000001" in flagged
    assert "USAAA0000002" in flagged
    assert "ISRC:USAAA0000001" in flagged
    assert "SPOTIFY:ISRC:USAAA0000001" in flagged


@pytest.mark.unit
def test_load_flagged_oct2025_empty_for_missing_path(tmp_path: Path) -> None:
    flagged = load_flagged_oct2025(tmp_path / "nope.csv")
    assert flagged == set()
