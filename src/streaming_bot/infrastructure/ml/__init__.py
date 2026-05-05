"""Adapters de infraestructura para ML.

Importes lazy: ``lightgbm`` y ``shap`` solo se importan dentro de los
métodos de los adapters, para que el resto del codebase no requiera la
extra ``ml`` para arrancar.
"""

from streaming_bot.infrastructure.ml.clickhouse_feature_repo import ClickhouseFeatureRepo
from streaming_bot.infrastructure.ml.lightgbm_predictor import LightGBMAnomalyPredictor
from streaming_bot.infrastructure.ml.lightgbm_trainer import LightGBMTrainer
from streaming_bot.infrastructure.ml.model_artifact import ModelArtifact, ModelMetadata

__all__ = [
    "ClickhouseFeatureRepo",
    "LightGBMAnomalyPredictor",
    "LightGBMTrainer",
    "ModelArtifact",
    "ModelMetadata",
]
