"""``TrackBrief``: encargo creativo para producir una pista AI.

Es un value object inmutable. La factoria de briefs garantiza variedad
(BPM, mood, longitud) dentro de un nicho dado.
"""

from __future__ import annotations

from dataclasses import dataclass

from streaming_bot.domain.value_objects import Country


@dataclass(frozen=True, slots=True)
class TrackBrief:
    """Encargo creativo para una sola pista.

    Atributos:
        niche: nicho del catalogo (lo-fi, sleep, ambient, study,
            white-noise, classical-ai).
        mood: estado emocional o atmosfera buscada (calm, dreamy, focus,
            melancholic, etc.).
        bpm_range: rango de tempo permitido al generador.
        duration_seconds: duracion objetivo en segundos.
        target_geos: tupla de paises para los que el brief tiene sentido.
        lyric_seed: semilla opcional para promo letras (None = instrumental).
    """

    niche: str
    mood: str
    bpm_range: tuple[int, int]
    duration_seconds: int
    target_geos: tuple[Country, ...]
    lyric_seed: str | None = None

    def __post_init__(self) -> None:
        if not self.niche:
            raise ValueError("niche no puede estar vacio")
        if not self.mood:
            raise ValueError("mood no puede estar vacio")
        low, high = self.bpm_range
        if low <= 0 or high <= 0:
            raise ValueError(f"bpm_range invalido: {self.bpm_range}")
        if low > high:
            raise ValueError(f"bpm_range invertido: {self.bpm_range}")
        if self.duration_seconds <= 0:
            raise ValueError(f"duration_seconds invalido: {self.duration_seconds}")
        if not self.target_geos:
            raise ValueError("target_geos no puede estar vacio")

    def average_bpm(self) -> int:
        low, high = self.bpm_range
        return (low + high) // 2

    def primary_geo(self) -> Country:
        return self.target_geos[0]
