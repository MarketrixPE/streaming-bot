"""Tests de los helpers de tipeo humano (puros, sin I/O)."""

from __future__ import annotations

from random import Random

import pytest

from streaming_bot.domain.persona import TypingProfile
from streaming_bot.infrastructure.browser.human_typing import (
    compute_keystroke_delays,
    inject_typos,
)


class TestComputeKeystrokeDelays:
    def test_returns_one_delay_per_char(self) -> None:
        profile = TypingProfile(avg_wpm=70, wpm_stddev=10, typo_probability_per_word=0.0)
        text = "hola mundo"
        delays = compute_keystroke_delays(text, profile=profile, rng=Random(0))
        assert len(delays) == len(text)
        assert all(d > 0.0 for d in delays)

    def test_average_delay_matches_profile_within_tolerance(self) -> None:
        # Promedio empírico ≈ 1 / chars_per_second con jitter razonable.
        profile = TypingProfile(avg_wpm=60)  # 60 wpm * 5 / 60 = 5 cps → 0.2s/char
        text = "x" * 500
        delays = compute_keystroke_delays(
            text,
            profile=profile,
            rng=Random(1),
            jitter_factor=0.1,
        )
        avg = sum(delays) / len(delays)
        assert 0.15 <= avg <= 0.30

    def test_pause_between_words_increases_total(self) -> None:
        # Con probabilidad alta de pausa, el delay total crece respecto al baseline.
        no_pause = TypingProfile(avg_wpm=70, pause_probability_between_words=0.0)
        with_pause = TypingProfile(avg_wpm=70, pause_probability_between_words=1.0)
        text = "uno dos tres cuatro cinco seis siete"
        rng_a = Random(5)
        rng_b = Random(5)
        a = sum(compute_keystroke_delays(text, profile=no_pause, rng=rng_a))
        b = sum(compute_keystroke_delays(text, profile=with_pause, rng=rng_b))
        assert b > a

    def test_invalid_profile_raises(self) -> None:
        # WPM 0 → cps 0 → debe explotar.
        profile = TypingProfile(avg_wpm=0)
        with pytest.raises(ValueError):
            compute_keystroke_delays("abc", profile=profile)


class TestInjectTypos:
    def test_zero_probability_means_no_typo(self) -> None:
        text = "hola mundo desde lima"
        segments = inject_typos(text, probability_per_word=0.0, rng=Random(42))
        # Reconstruir el texto a partir de los segmentos no-typo:
        reconstructed = "".join(chunk for chunk, is_typo in segments if not is_typo)
        assert reconstructed == text
        assert all(not is_typo for _, is_typo in segments)

    def test_full_probability_yields_typos_for_long_words(self) -> None:
        text = "hola buenos dias amigos desarrolladores"
        segments = inject_typos(text, probability_per_word=1.0, rng=Random(0))
        typo_count = sum(1 for _, is_typo in segments if is_typo)
        # 5 palabras, todas largas (>2 chars) → todas deberían marcarse.
        assert typo_count == 5

    def test_probability_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError):
            inject_typos("abc", probability_per_word=1.5)

    def test_short_words_are_not_typoed(self) -> None:
        text = "ab cd ef"  # todas <= 2 chars
        segments = inject_typos(text, probability_per_word=1.0, rng=Random(7))
        assert all(not is_typo for _, is_typo in segments)

    def test_empty_text_returns_empty_list(self) -> None:
        assert inject_typos("", probability_per_word=0.5) == []

    def test_deterministic_with_same_seed(self) -> None:
        text = "hola buenas tardes equipo"
        a = inject_typos(text, probability_per_word=0.5, rng=Random(99))
        b = inject_typos(text, probability_per_word=0.5, rng=Random(99))
        assert a == b
