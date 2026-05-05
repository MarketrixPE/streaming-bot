"""Submodulo de A/B testing del dominio.

Define los value objects y agregados necesarios para correr experimentos
sobre variantes de comportamiento (mouse profile, typing speed, hover dwell,
save_rate, geo routing thresholds, etc.) sin acoplarse a la infraestructura.

Reglas:
- Sin I/O: ningun import a infraestructura.
- VOs son ``frozen + slots`` para inmutabilidad estructural.
- ``Experiment`` es el agregado raiz: encapsula transiciones de estado validas.
"""

from streaming_bot.domain.experiments.assignment import VariantAssignment
from streaming_bot.domain.experiments.experiment import (
    Experiment,
    ExperimentStatus,
    MetricsTargets,
)
from streaming_bot.domain.experiments.outcome import ExperimentOutcome
from streaming_bot.domain.experiments.variant import Variant

__all__ = [
    "Experiment",
    "ExperimentOutcome",
    "ExperimentStatus",
    "MetricsTargets",
    "Variant",
    "VariantAssignment",
]
