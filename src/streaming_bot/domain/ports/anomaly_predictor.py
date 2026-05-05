"""Puerto del predictor de anomalías.

El dominio define la interfaz; cada adapter de infraestructura se la
implementa con su modelo concreto (LightGBM, XGBoost, ONNX runtime, etc).

El servicio de aplicación solo depende de este protocolo; nunca importa
``lightgbm`` ni ``shap`` directamente.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from streaming_bot.domain.ml.anomaly_score import AnomalyScore
from streaming_bot.domain.ml.feature_vector import AccountFeatureVector


@runtime_checkable
class IAnomalyPredictor(Protocol):
    """Predictor de score de baneo en próximas 24-48h.

    Los métodos ``predict_for_account`` y ``predict_batch`` reciben un
    ``account_id`` (o lista) y devuelven un ``AnomalyScore`` por cuenta.
    El predictor es responsable de:
    - Pedir el ``AccountFeatureVector`` a través del extractor.
    - Cachear resultados (TTL típico 30 min).
    - Calcular SHAP top-3 features para explainability.

    ``predict_from_features`` permite inferir directamente sobre un VO ya
    construido (útil en tests y en el batch trainer).
    """

    async def predict_for_account(self, account_id: str) -> AnomalyScore: ...

    async def predict_batch(self, account_ids: list[str]) -> list[AnomalyScore]: ...

    async def predict_from_features(
        self,
        features: AccountFeatureVector,
    ) -> AnomalyScore: ...

    @property
    def model_version(self) -> str: ...
