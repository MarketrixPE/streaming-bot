"""Predictor LightGBM con SHAP top-3 features y caché in-memory.

- Modelo cargado desde disco vía ``ModelArtifact``.
- Cache TTL en memoria por ``account_id`` para evitar inferencias
  duplicadas en ráfaga (default 30 minutos).
- SHAP top-3 features: usamos el método nativo de LightGBM
  (``predict(..., pred_contrib=True)``) que es órdenes de magnitud más
  rápido que ``shap.TreeExplainer`` y no requiere la dependencia ``shap``
  para inferencia.

Concurrencia: las predicciones son CPU-bound. Para batches grandes el
caller debe orquestar ``asyncio.gather`` con un pool de threads o
limitar el batch size.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from streaming_bot.domain.ml.anomaly_score import (
    AnomalyScore,
    FeatureContribution,
)
from streaming_bot.domain.ml.feature_vector import FEATURE_NAMES, AccountFeatureVector
from streaming_bot.domain.ports.anomaly_predictor import IAnomalyPredictor

if TYPE_CHECKING:
    from collections.abc import Callable

    from streaming_bot.application.ml.feature_extractor import FeatureExtractor
    from streaming_bot.infrastructure.ml.model_artifact import ModelArtifact


class LightGBMAnomalyPredictor(IAnomalyPredictor):
    """Predictor LightGBM con SHAP top-3 y caché TTL.

    El cache es in-memory; el caller puede envolver con un decorador
    Redis si necesita compartirlo entre procesos.
    """

    def __init__(
        self,
        *,
        artifact: ModelArtifact,
        feature_extractor: FeatureExtractor,
        cache_ttl_seconds: float = 1800.0,
        threshold_medium: float = 0.4,
        threshold_high: float = 0.7,
        threshold_critical: float = 0.85,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._artifact = artifact
        self._extractor = feature_extractor
        self._cache_ttl = cache_ttl_seconds
        self._threshold_medium = threshold_medium
        self._threshold_high = threshold_high
        self._threshold_critical = threshold_critical
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self._cache: dict[str, tuple[float, AnomalyScore]] = {}
        self._lock = asyncio.Lock()

    @property
    def model_version(self) -> str:
        return self._artifact.metadata.model_version

    async def predict_for_account(self, account_id: str) -> AnomalyScore:
        cached = self._get_cached(account_id)
        if cached is not None:
            return cached
        features = await self._extractor.extract(account_id)
        score = await self.predict_from_features(features)
        await self._set_cached(account_id, score)
        return score

    async def predict_batch(self, account_ids: list[str]) -> list[AnomalyScore]:
        tasks = [self.predict_for_account(aid) for aid in account_ids]
        return list(await asyncio.gather(*tasks))

    async def predict_from_features(
        self,
        features: AccountFeatureVector,
    ) -> AnomalyScore:
        """Inferencia pura: features → score con SHAP top-3."""
        return await asyncio.to_thread(self._predict_sync, features)

    def _predict_sync(self, features: AccountFeatureVector) -> AnomalyScore:
        """Inferencia sincronicha (bloqueante, ejecutada en thread)."""
        import numpy as np

        x = np.asarray([features.as_array()], dtype=np.float32)
        if self._artifact.scaler is not None:
            x = self._artifact.scaler.transform(x)
        proba_raw = self._artifact.model.predict(x)
        proba = float(np.asarray(proba_raw).reshape(-1)[0])
        proba = max(0.0, min(1.0, proba))
        top_features = self._compute_shap_top(features=x)
        return AnomalyScore.from_score(
            account_id=features.account_id,
            score=proba,
            computed_at=self._now_factory(),
            top_features=top_features,
            model_version=self._artifact.metadata.model_version,
            threshold_medium=self._threshold_medium,
            threshold_high=self._threshold_high,
            threshold_critical=self._threshold_critical,
        )

    def _compute_shap_top(
        self,
        *,
        features: Any,
        top_k: int = 3,
    ) -> tuple[FeatureContribution, ...]:
        """Top-k contribuciones SHAP usando ``pred_contrib`` de LightGBM."""
        import numpy as np

        contribs_raw = self._artifact.model.predict(features, pred_contrib=True)
        contribs = np.asarray(contribs_raw).reshape(-1)
        # El último elemento es el bias; lo descartamos.
        per_feature = contribs[: len(FEATURE_NAMES)]
        ranked = sorted(
            zip(FEATURE_NAMES, per_feature, strict=True),
            key=lambda pair: abs(float(pair[1])),
            reverse=True,
        )
        return tuple(
            FeatureContribution(feature_name=name, contribution=float(value))
            for name, value in ranked[:top_k]
        )

    def _get_cached(self, account_id: str) -> AnomalyScore | None:
        entry = self._cache.get(account_id)
        if entry is None:
            return None
        timestamp, score = entry
        if time.monotonic() - timestamp > self._cache_ttl:
            self._cache.pop(account_id, None)
            return None
        return score

    async def _set_cached(self, account_id: str, score: AnomalyScore) -> None:
        async with self._lock:
            self._cache[account_id] = (time.monotonic(), score)
