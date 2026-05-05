"""Tests del ``NicheBriefFactory``.

Verifican:
- Numero de briefs.
- Diversidad de bpm/duration en muestreo grande con seed fija.
- Errores controlados con niche desconocido o count invalido.
- Override de ``target_geos`` y ``lyric_seed``.
"""

from __future__ import annotations

import random

import pytest

from streaming_bot.application.catalog_pipeline.brief_factory import (
    NICHE_PRESETS,
    NicheBriefFactory,
)
from streaming_bot.domain.value_objects import Country


def _factory(seed: int = 42) -> NicheBriefFactory:
    return NicheBriefFactory(rng=random.Random(seed))


class TestNicheBriefFactory:
    def test_generates_requested_count(self) -> None:
        briefs = _factory().build("lo-fi", count=10)
        assert len(briefs) == 10
        assert all(b.niche == "lo-fi" for b in briefs)

    def test_diversifies_bpm_and_duration(self) -> None:
        briefs = _factory().build("lo-fi", count=50)
        bpm_ranges = {b.bpm_range for b in briefs}
        durations = {b.duration_seconds for b in briefs}
        assert len(bpm_ranges) >= 2
        assert len(durations) >= 2

    def test_target_geos_override_applies(self) -> None:
        briefs = _factory().build(
            "lo-fi",
            count=3,
            target_geos=(Country.PE, Country.AR),
        )
        for brief in briefs:
            assert brief.target_geos == (Country.PE, Country.AR)
            assert brief.primary_geo() is Country.PE

    def test_default_geos_when_no_override(self) -> None:
        briefs = _factory().build("ambient", count=2)
        expected_geos = NICHE_PRESETS["ambient"].default_geos
        assert briefs[0].target_geos == expected_geos

    def test_instrumental_preset_drops_lyric_seed(self) -> None:
        briefs = _factory().build("sleep", count=5, lyric_seed="ignored")
        assert all(b.lyric_seed is None for b in briefs)

    def test_unknown_niche_raises(self) -> None:
        with pytest.raises(ValueError, match="niche desconocido"):
            _factory().build("hyperpop", count=1)

    def test_invalid_count_raises(self) -> None:
        with pytest.raises(ValueError, match="count debe ser >0"):
            _factory().build("lo-fi", count=0)

    def test_seed_is_reproducible(self) -> None:
        first = _factory(seed=99).build("study", count=8)
        second = _factory(seed=99).build("study", count=8)
        assert [b.bpm_range for b in first] == [b.bpm_range for b in second]
        assert [b.duration_seconds for b in first] == [b.duration_seconds for b in second]

    def test_mood_uniqueness_within_batch(self) -> None:
        # El factory garantiza moods unicos via sufijo de indice cuando
        # hay colisiones, asi el LLM no recibe el mismo mood dos veces.
        briefs = _factory().build("lo-fi", count=8)
        moods = [b.mood for b in briefs]
        assert len(moods) == len(set(moods))
