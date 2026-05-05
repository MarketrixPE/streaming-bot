"""Capa de aplicación: orquesta el predictor con políticas de retiro.

Componentes:
- ``AnomalyDetectionService``: combina el predictor con el threshold de
  cuarentena para emitir señales de retiro preventivo a los workers.
- ``FeatureExtractor``: cruza Postgres y ClickHouse para construir
  ``AccountFeatureVector`` por cuenta.
- ``TrainModelUseCase``: orquesta el entrenamiento periódico (CV,
  hyperopt simple, persistencia del artefacto).
"""

from streaming_bot.application.ml.anomaly_service import (
    AnomalyDetectionService,
    QuarantineDecision,
    QuarantineSignaler,
)
from streaming_bot.application.ml.feature_extractor import (
    FeatureExtractor,
    IClickhouseFeatureRepo,
)
from streaming_bot.application.ml.training_orchestrator import (
    LabeledFeatureSample,
    TrainingDataset,
    TrainingReport,
    TrainModelUseCase,
)

__all__ = [
    "AnomalyDetectionService",
    "FeatureExtractor",
    "IClickhouseFeatureRepo",
    "LabeledFeatureSample",
    "QuarantineDecision",
    "QuarantineSignaler",
    "TrainModelUseCase",
    "TrainingDataset",
    "TrainingReport",
]
