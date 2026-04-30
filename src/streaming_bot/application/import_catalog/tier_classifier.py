"""Clasificador de tiers de canciones y deteccion de spikes.

Reglas de negocio (single source of truth):
    HOT     -> avg_streams_per_month > 100k       (NO boostear, ya rinde)
    RISING  -> 10k - 100k                         (NO boostear)
    MID     -> 1k - 10k                           (boost moderado candidato)
    LOW     -> 100 - 1k                           (boost prioritario)
    ZOMBIE  -> < 100 en Spotify pero >X en social (potencial dormido)
    DEAD    -> 0                                  (descartado)
    FLAGGED -> Override por listado de canciones flagged historicamente
              (ej. ``data/flagged_oct2025.csv``).

El classifier es puro (sin I/O) — el caller proporciona el ``flagged_set``
ya cargado para mantener la responsabilidad de I/O fuera del dominio.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from streaming_bot.application.import_catalog.parsers import ParsedCatalogRow
from streaming_bot.domain.song import SongTier

# ── Umbrales (constantes nombradas para evitar magic numbers) ─────────────────
TIER_HOT_MIN: Final[float] = 100_000.0
TIER_RISING_MIN: Final[float] = 10_000.0
TIER_MID_MIN: Final[float] = 1_000.0
TIER_LOW_MIN: Final[float] = 100.0
SPIKE_THRESHOLD_PCT: Final[float] = 300.0
"""% de aumento mes-a-mes que dispara un flag por spike."""
ZOMBIE_SOCIAL_MIN: Final[int] = 500
"""Streams en plataformas no-Spotify para considerar potencial 'zombie'."""


@dataclass(frozen=True, slots=True)
class FlagCheck:
    """Resultado del chequeo de spike/flag para una row."""

    flagged: bool
    reason: str


class TierClassifier:
    """Clasifica canciones en tiers y detecta spikes anomalos.

    Es una clase puramente funcional (estado vacio); modelada como clase para
    permitir overrides de umbrales en tests/staging via subclase.
    """

    def __init__(
        self,
        *,
        hot_min: float = TIER_HOT_MIN,
        rising_min: float = TIER_RISING_MIN,
        mid_min: float = TIER_MID_MIN,
        low_min: float = TIER_LOW_MIN,
        spike_threshold_pct: float = SPIKE_THRESHOLD_PCT,
        zombie_social_min: int = ZOMBIE_SOCIAL_MIN,
    ) -> None:
        self._hot_min = hot_min
        self._rising_min = rising_min
        self._mid_min = mid_min
        self._low_min = low_min
        self._spike_threshold_pct = spike_threshold_pct
        self._zombie_social_min = zombie_social_min

    # ── API publica ──────────────────────────────────────────────────────────
    def classify(self, row: ParsedCatalogRow) -> SongTier:
        """Devuelve el tier que corresponde a la cancion segun heuristica.

        Reglas de orden:
        1. ``avg_streams_per_month == 0`` -> DEAD
        2. Spotify <100 + social >=zombie_social_min -> ZOMBIE
        3. avg comparado contra umbrales HOT/RISING/MID/LOW
        4. Si avg >0 pero <LOW, cae a ZOMBIE/DEAD segun social
        """
        avg = row.avg_streams_per_month
        if avg <= 0 and row.total_streams <= 0:
            return SongTier.DEAD

        bracket = self._bracket_for_avg(avg)
        if bracket is not None:
            return bracket

        # avg < LOW: inspeccionamos potencial zombie/social.
        spotify_dead = row.spotify_streams_total < int(self._low_min)
        has_social_signal = row.non_spotify_streams_total >= self._zombie_social_min
        if spotify_dead and has_social_signal:
            return SongTier.ZOMBIE
        return SongTier.DEAD if avg <= 0 else SongTier.ZOMBIE

    def _bracket_for_avg(self, avg: float) -> SongTier | None:
        """Devuelve el tier por umbral lineal o ``None`` si avg<LOW."""
        if avg >= self._hot_min:
            return SongTier.HOT
        if avg >= self._rising_min:
            return SongTier.RISING
        if avg >= self._mid_min:
            return SongTier.MID
        if avg >= self._low_min:
            return SongTier.LOW
        return None

    def detect_spike(
        self,
        row: ParsedCatalogRow,
        history: list[float],
    ) -> tuple[bool, str]:
        """Devuelve ``(flagged, reason)`` si hay spike mes-a-mes >umbral.

        Args:
            row: La cancion siendo evaluada (la mas reciente).
            history: Streams mensuales en orden cronologico (mas antiguo
                primero, mas reciente al final). Se compara el ultimo valor
                contra el promedio anterior.
        """
        if not history or len(history) < 2:
            return False, ""
        latest = history[-1]
        prior = history[:-1]
        baseline = sum(prior) / len(prior)
        if baseline <= 0:
            return False, ""
        delta_pct = (latest - baseline) / baseline * 100.0
        if delta_pct >= self._spike_threshold_pct:
            return True, (
                f"spike_detected: {delta_pct:.0f}% sobre baseline "
                f"({latest:.0f} vs avg {baseline:.0f})"
            )
        if row.spike_ratio >= self._spike_threshold_pct / 100.0:
            return True, (f"spike_ratio_anomalo: {row.spike_ratio:.2f}x mes pico vs resto")
        return False, ""

    @staticmethod
    def is_flagged_oct2025(spotify_uri: str, flagged_set: set[str]) -> bool:
        """Chequea si la identidad esta en el set de flagged historico.

        El set debe contener identidades estables (ISRC normalizado o
        ``spotify:track:...``). El caller construye el set via
        ``load_flagged_oct2025`` para mantener I/O fuera del dominio.
        """
        if not spotify_uri:
            return False
        return spotify_uri.strip().upper() in flagged_set


def load_flagged_oct2025(path: Path) -> set[str]:
    """Carga el CSV de canciones flaggeadas en Oct'25 a un set indexado por ISRC.

    El CSV tiene columna ``ID`` con el ISRC. Devolvemos las identidades
    normalizadas en mayusculas para comparar contra ``stable_key`` y URIs
    sintetizadas indistintamente.
    """
    if not path.exists():
        return set()
    df = pd.read_csv(path)
    flagged: set[str] = set()
    for value in df.get("ID", pd.Series(dtype=str)):
        if isinstance(value, str):
            isrc = value.strip().upper()
            if isrc:
                flagged.add(isrc)
                flagged.add(f"ISRC:{isrc}")
                flagged.add(f"SPOTIFY:ISRC:{isrc}")
    return flagged


__all__ = [
    "SPIKE_THRESHOLD_PCT",
    "TIER_HOT_MIN",
    "TIER_LOW_MIN",
    "TIER_MID_MIN",
    "TIER_RISING_MIN",
    "ZOMBIE_SOCIAL_MIN",
    "FlagCheck",
    "TierClassifier",
    "load_flagged_oct2025",
]
