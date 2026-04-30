"""Helpers puros para tipeo humano: delays por keystroke + inyección de typos.

No tocan I/O ni Playwright. El consumidor (`CamoufoxSession.human_type`) los
combina con `page.keyboard.type` + delays + backspaces.
"""

from __future__ import annotations

from random import Random

from streaming_bot.domain.persona import TypingProfile


def compute_keystroke_delays(
    text: str,
    *,
    profile: TypingProfile,
    rng: Random | None = None,
    jitter_factor: float = 0.30,
    word_pause_min_s: float = 0.10,
    word_pause_max_s: float = 0.40,
) -> list[float]:
    """Devuelve un delay (segundos) por carácter del texto.

    El delay base por carácter sale de `profile.chars_per_second()`. A cada
    delay se le aplica jitter gaussiano. En los límites de palabra (espacio)
    hay probabilidad `profile.pause_probability_between_words` de añadir
    una pausa adicional uniforme entre `word_pause_min_s` y `word_pause_max_s`.
    """
    rng = rng if rng is not None else Random()  # noqa: S311

    cps = profile.chars_per_second()
    if cps <= 0.0:
        raise ValueError("chars_per_second debe ser > 0")
    base_delay_s = 1.0 / cps

    delays: list[float] = []
    for ch in text:
        jittered = rng.gauss(base_delay_s, base_delay_s * jitter_factor)
        delay = max(base_delay_s * 0.2, jittered)
        if ch == " " and rng.random() < profile.pause_probability_between_words:
            delay += rng.uniform(word_pause_min_s, word_pause_max_s)
        delays.append(delay)
    return delays


def inject_typos(
    text: str,
    *,
    probability_per_word: float,
    rng: Random | None = None,
) -> list[tuple[str, bool]]:
    """Devuelve segmentos `(chunk, is_typo)` para tipear el texto.

    Si `is_typo=True`, el caller debe tipear el chunk y luego enviar
    `len(chunk)` backspaces para borrarlo (simula corrección). El siguiente
    chunk reescribe la palabra correcta entera.

    No se inyectan typos en palabras de longitud <=2 ni en el último carácter.
    """
    if not 0.0 <= probability_per_word <= 1.0:
        raise ValueError("probability_per_word debe estar en [0,1]")
    rng = rng if rng is not None else Random()  # noqa: S311

    if not text:
        return []

    words = text.split(" ")
    segments: list[tuple[str, bool]] = []

    for word_index, word in enumerate(words):
        if len(word) > 2 and rng.random() < probability_per_word:
            # Inyecta un typo en una posición intermedia.
            pos = rng.randint(1, len(word) - 1)
            wrong_char = chr(rng.randint(ord("a"), ord("z")))
            wrong_chunk = word[:pos] + wrong_char
            segments.append((wrong_chunk, True))
            segments.append((word, False))
        else:
            segments.append((word, False))
        if word_index < len(words) - 1:
            segments.append((" ", False))
    return segments
