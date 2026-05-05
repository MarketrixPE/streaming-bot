"""Tests unitarios de `AcpsScore`.

Validamos:
- Cada factor parcial se calcula correctamente.
- Saturacion al 100% cuando el observado >= umbral.
- Score final es la combinacion ponderada documentada (0.4/0.3/0.2/0.1).
- Casos limite: historial vacio (score 0) y profile con threshold 0 (factor 1).
"""

from __future__ import annotations

import pytest

from streaming_bot.domain.deezer import (
    AcpsScore,
    AcpsScoreFactors,
    DeezerListenerHistory,
    SuperFanProfile,
)


class TestAcpsScoreFactorsValidation:
    def test_factor_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="replay_factor"):
            AcpsScoreFactors(
                replay_factor=1.5,
                session_length_factor=0.5,
                catalog_breadth_factor=0.5,
                artist_diversity_factor=0.5,
            )

    def test_negative_factor_raises(self) -> None:
        with pytest.raises(ValueError, match="catalog_breadth_factor"):
            AcpsScoreFactors(
                replay_factor=0.5,
                session_length_factor=0.5,
                catalog_breadth_factor=-0.1,
                artist_diversity_factor=0.5,
            )


class TestAcpsScoreFromHistory:
    def test_empty_history_yields_zero_score(self) -> None:
        history = DeezerListenerHistory(account_id="x")
        score = AcpsScore.from_history(history, SuperFanProfile())
        assert score.value == 0.0
        assert score.likely_boosted is False

    def test_perfect_super_fan_yields_score_one(self) -> None:
        profile = SuperFanProfile()
        history = DeezerListenerHistory(
            account_id="x",
            artists_followed=tuple(f"a-{i}" for i in range(80)),
            avg_session_minutes_30d=90.0,
            replay_rate=0.6,
            distinct_tracks_30d=400,
            distinct_albums_30d=60,
        )
        score = AcpsScore.from_history(history, profile)
        assert score.value == pytest.approx(1.0)
        assert score.likely_boosted is True
        assert score.factors.replay_factor == 1.0
        assert score.factors.session_length_factor == 1.0
        assert score.factors.catalog_breadth_factor == 1.0
        assert score.factors.artist_diversity_factor == 1.0

    def test_partial_history_combines_weights_correctly(self) -> None:
        profile = SuperFanProfile()
        history = DeezerListenerHistory(
            account_id="x",
            artists_followed=tuple(f"a-{i}" for i in range(25)),  # 50% del umbral 50
            avg_session_minutes_30d=22.5,  # 50% del umbral 45
            replay_rate=0.15,  # 50% del umbral 0.30
            distinct_tracks_30d=100,  # 50% del umbral 200
            distinct_albums_30d=15,  # 50% del umbral 30
        )
        score = AcpsScore.from_history(history, profile)
        # Cada factor 0.5; suma ponderada = 0.4*0.5 + 0.3*0.5 + 0.2*0.5 + 0.1*0.5 = 0.5.
        assert score.value == pytest.approx(0.5)
        assert score.likely_boosted is False
        assert score.factors.replay_factor == pytest.approx(0.5)
        assert score.factors.session_length_factor == pytest.approx(0.5)
        assert score.factors.catalog_breadth_factor == pytest.approx(0.5)
        assert score.factors.artist_diversity_factor == pytest.approx(0.5)

    def test_replay_dominates_due_to_weight(self) -> None:
        """Si solo cumple replay_rate, el score deberia ser ~0.4 (peso del replay)."""
        profile = SuperFanProfile()
        history = DeezerListenerHistory(
            account_id="x",
            replay_rate=0.4,  # supera 0.30 -> factor 1.0
        )
        score = AcpsScore.from_history(history, profile)
        # Solo replay aporta: 0.4 * 1.0 = 0.4. Otros factores en 0.
        assert score.value == pytest.approx(0.4)
        assert score.factors.replay_factor == 1.0
        assert score.factors.session_length_factor == 0.0

    def test_zero_threshold_treated_as_satisfied(self) -> None:
        """Si SuperFanProfile relaja un threshold a 0, ese factor debe saturar a 1.

        Construimos un profile con replay_rate_min minimo positivo (la validacion
        rechaza 0) pero forzamos los demas a un threshold relajado para ver el
        comportamiento de saturacion estable.
        """
        profile = SuperFanProfile(
            artists_followed_min=0,
            avg_session_minutes_min=0.0,
            replay_rate_min=0.01,
            distinct_tracks_30d_min=0,
            distinct_albums_30d_min=0,
        )
        history = DeezerListenerHistory(
            account_id="x",
            replay_rate=0.5,
        )
        score = AcpsScore.from_history(history, profile)
        # Todos los factores excepto replay valen 1.0 por threshold 0.
        # Replay tambien satura porque 0.5 >> 0.01. Score = 1.0.
        assert score.value == pytest.approx(1.0)
