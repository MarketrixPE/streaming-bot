"""Configuración para el composer de playlists."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ComposerConfig:
    """Configuración del compositor de playlists.

    Controla la estrategia de mezcla target+camuflaje y anti-contiguidad.
    """

    min_camouflage_between_targets: int = 2
    """Nunca dos targets contiguos (al menos N camuflaje entre targets)."""

    avoid_first_track_target: bool = True
    """Primer track siempre camuflaje (comportamiento más natural)."""

    target_ratio_jitter: float = 0.05
    """±5% del ratio pedido para evitar patrones detectables."""

    rng_seed: int | None = None
    """Seed para reproducibilidad (tests). None = aleatorio."""
