"""Capa de aplicacion del framework de A/B testing.

Orquesta el ciclo de vida de experimentos, la asignacion deterministica de
variantes y el analisis de outcomes con feedback loop hacia los defaults.
"""

from streaming_bot.application.experiments.analyzer import (
    ExperimentAnalyzer,
    IExperimentEventsReader,
    RawVariantMetrics,
)
from streaming_bot.application.experiments.assignment_service import (
    DEFAULT_ASSIGNMENT_SALT,
    ExperimentAssignmentService,
)
from streaming_bot.application.experiments.experiment_service import (
    ExperimentService,
    ISettingsOverridesWriter,
)
from streaming_bot.application.experiments.variant_resolver import VariantResolver

__all__ = [
    "DEFAULT_ASSIGNMENT_SALT",
    "ExperimentAnalyzer",
    "ExperimentAssignmentService",
    "ExperimentService",
    "IExperimentEventsReader",
    "ISettingsOverridesWriter",
    "RawVariantMetrics",
    "VariantResolver",
]
