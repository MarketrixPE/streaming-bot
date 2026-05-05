"""Subdominio de Machine Learning: detección anticipada de baneos.

Este paquete contiene los value objects y puertos del subdominio ML.
NO importa nada de infraestructura ni de bibliotecas pesadas (lightgbm,
shap, sklearn). El dominio se mantiene puro y testeable sin depender de
artefactos entrenados.

Componentes:
- ``AnomalyScore``: VO con score 0..1 + risk_level + top_features.
- ``AccountFeatureVector``: VO con todas las features que el modelo
  consume para predecir el riesgo de baneo en las próximas 24-48h.
- ``IAnomalyPredictor``: puerto que la infraestructura implementa con
  el modelo LightGBM cargado desde disco.
"""

from streaming_bot.domain.ml.anomaly_score import AnomalyScore, RiskLevel
from streaming_bot.domain.ml.feature_vector import AccountFeatureVector

__all__ = [
    "AccountFeatureVector",
    "AnomalyScore",
    "RiskLevel",
]
