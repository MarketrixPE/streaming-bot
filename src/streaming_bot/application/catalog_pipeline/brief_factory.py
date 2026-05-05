"""``NicheBriefFactory``: produce N ``TrackBrief`` por nicho.

Cada nicho define un preset con BPM, moods, duraciones y geos por defecto.
La factoria muestrea con ``random.Random`` (seed-controlable) para que los
tests sean deterministas.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from streaming_bot.domain.catalog_pipeline.track_brief import TrackBrief
from streaming_bot.domain.value_objects import Country


@dataclass(frozen=True, slots=True)
class NichePreset:
    """Plantilla con dimensiones de variacion para un nicho.

    El factory escoge una combinacion al azar para cada brief, garantizando
    diversidad dentro de los rangos del preset.
    """

    niche: str
    bpm_buckets: tuple[tuple[int, int], ...]
    moods: tuple[str, ...]
    duration_buckets: tuple[int, ...]
    default_geos: tuple[Country, ...]
    instrumental: bool = True


# Cada preset esta calibrado para los nichos mas rentables en
# streaming "background music" (lo-fi study, deep-sleep, white noise, etc.).
NICHE_PRESETS: dict[str, NichePreset] = {
    "lo-fi": NichePreset(
        niche="lo-fi",
        bpm_buckets=((70, 75), (76, 80), (81, 86), (87, 92)),
        moods=("chill", "rainy", "late-night", "study"),
        duration_buckets=(90, 120, 150, 180, 210, 240),
        default_geos=(Country.US, Country.MX, Country.PE, Country.ES),
    ),
    "sleep": NichePreset(
        niche="sleep",
        bpm_buckets=((40, 50), (51, 60)),
        moods=("dreamy", "weightless", "deep-sleep", "lullaby"),
        duration_buckets=(300, 420, 540, 600),
        default_geos=(Country.US, Country.GB, Country.DE, Country.MX),
    ),
    "ambient": NichePreset(
        niche="ambient",
        bpm_buckets=((50, 60), (61, 70), (71, 80)),
        moods=("ethereal", "spacey", "calm", "introspective"),
        duration_buckets=(180, 240, 300, 360, 480),
        default_geos=(Country.US, Country.DE, Country.FR, Country.JP),
    ),
    "study": NichePreset(
        niche="study",
        bpm_buckets=((85, 95), (96, 105), (106, 115)),
        moods=("focus", "deep-work", "productive", "concentration"),
        duration_buckets=(180, 210, 240, 270, 300),
        default_geos=(Country.US, Country.MX, Country.PE, Country.ES, Country.GB),
    ),
    "white-noise": NichePreset(
        niche="white-noise",
        bpm_buckets=((50, 50),),
        moods=("brown-noise", "pink-noise", "white-noise", "rain"),
        duration_buckets=(600, 1200, 1800, 3600),
        default_geos=(Country.US, Country.GB, Country.DE),
    ),
    "classical-ai": NichePreset(
        niche="classical-ai",
        bpm_buckets=((60, 70), (71, 84), (85, 100), (101, 120)),
        moods=("baroque", "romantic", "minimalist", "neoclassical"),
        duration_buckets=(180, 240, 300, 360),
        default_geos=(Country.US, Country.DE, Country.FR, Country.IT, Country.JP),
    ),
}


class NicheBriefFactory:
    """Genera ``TrackBrief`` con BPM/mood/duracion variados por nicho.

    El factory acepta un ``random.Random`` inyectable para que la salida sea
    reproducible en tests (semilla fija) y suficientemente variada en prod.
    """

    def __init__(
        self,
        *,
        presets: dict[str, NichePreset] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._presets = presets or NICHE_PRESETS

        self._rng = rng or random.Random()  # noqa: S311

    def build(
        self,
        niche: str,
        count: int,
        *,
        target_geos: tuple[Country, ...] | None = None,
        lyric_seed: str | None = None,
    ) -> list[TrackBrief]:
        """Devuelve ``count`` briefs para ``niche``.

        Args:
            niche: clave del preset (ej. ``lo-fi``, ``sleep``).
            count: numero de briefs a generar.
            target_geos: override de los geos por defecto del preset.
            lyric_seed: si el preset es vocal-friendly, semilla de letra.

        Raises:
            ValueError: si ``niche`` no existe o ``count`` <= 0.
        """
        if count <= 0:
            raise ValueError(f"count debe ser >0, recibido {count}")
        preset = self._presets.get(niche)
        if preset is None:
            available = sorted(self._presets.keys())
            raise ValueError(f"niche desconocido: {niche}. Disponibles: {available}")

        geos = target_geos or preset.default_geos
        if not geos:
            raise ValueError(f"target_geos vacio para niche={niche}")

        briefs: list[TrackBrief] = []
        for index in range(count):
            bpm_range = self._rng.choice(preset.bpm_buckets)
            mood = self._rng.choice(preset.moods)
            duration = self._rng.choice(preset.duration_buckets)
            briefs.append(
                TrackBrief(
                    niche=preset.niche,
                    mood=self._mood_with_index(mood, index),
                    bpm_range=bpm_range,
                    duration_seconds=duration,
                    target_geos=geos,
                    lyric_seed=lyric_seed if not preset.instrumental else None,
                ),
            )
        return briefs

    @staticmethod
    def _mood_with_index(mood: str, index: int) -> str:
        """Asegura mood unico aniadiendo sufijo cuando hay colisiones."""
        if index == 0:
            return mood
        return f"{mood}-{index}"
