"""Entrenador LightGBM con CV time-series y hyperopt simple.

Estrategia:
- Ordenamos las muestras por ``observed_at`` y hacemos
  ``TimeSeriesSplit`` (5 folds) — evita data leakage.
- Hyperopt manual sobre un grid pequeño: probamos una lista finita de
  combinaciones razonables sobre ``num_leaves``, ``learning_rate``,
  ``min_data_in_leaf``, ``max_depth``. No usamos optuna para mantener
  dependencias mínimas.
- Métrica objetivo: AUC-ROC media sobre folds.
- ``class_weight='balanced'`` para handle desbalance (muy pocas cuentas
  son baneadas).
- Guardamos el artefacto y devolvemos un ``TrainingReport``.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from streaming_bot.application.ml.training_orchestrator import (
    IModelTrainer,
    TrainingDataset,
    TrainingReport,
)
from streaming_bot.domain.ml.feature_vector import FEATURE_NAMES
from streaming_bot.infrastructure.ml.model_artifact import ModelArtifact, ModelMetadata

if TYPE_CHECKING:
    from collections.abc import Sequence


_DEFAULT_GRID: tuple[dict[str, float | int], ...] = (
    {"num_leaves": 31, "learning_rate": 0.05, "min_data_in_leaf": 20, "max_depth": -1},
    {"num_leaves": 63, "learning_rate": 0.05, "min_data_in_leaf": 20, "max_depth": 8},
    {"num_leaves": 31, "learning_rate": 0.1, "min_data_in_leaf": 50, "max_depth": -1},
    {"num_leaves": 127, "learning_rate": 0.03, "min_data_in_leaf": 10, "max_depth": 10},
)


@dataclass(frozen=True, slots=True)
class _FoldResult:
    fold: int
    auc: float


class LightGBMTrainer(IModelTrainer):
    """Trainer que produce un ``ModelArtifact`` listo para servir."""

    def __init__(
        self,
        *,
        artifact_dir: Path,
        model_version: str = "v0.1.0",
        n_splits: int = 5,
        n_estimators: int = 200,
        early_stopping_rounds: int = 20,
        random_state: int = 42,
        param_grid: Sequence[dict[str, float | int]] | None = None,
    ) -> None:
        if n_splits < 2:
            raise ValueError(f"n_splits debe ser >= 2: {n_splits}")
        self._artifact_dir = artifact_dir
        self._model_version = model_version
        self._n_splits = n_splits
        self._n_estimators = n_estimators
        self._early_stopping_rounds = early_stopping_rounds
        self._random_state = random_state
        self._grid = tuple(param_grid) if param_grid else _DEFAULT_GRID

    def train(self, dataset: TrainingDataset) -> TrainingReport:
        """Entrena con CV + hyperopt simple y persiste el artefacto."""
        import numpy as np

        sorted_samples = sorted(dataset.samples, key=lambda s: s.observed_at)
        x = np.asarray(
            [s.features.as_array() for s in sorted_samples],
            dtype=np.float32,
        )
        y = np.asarray([s.label for s in sorted_samples], dtype=np.int32)
        if x.shape[0] < self._n_splits + 1:
            raise ValueError(
                f"muestras insuficientes para CV: {x.shape[0]} < {self._n_splits + 1}",
            )

        best_params, best_auc, best_std = self._hyperopt(x=x, y=y)

        final_model = self._fit_final(x=x, y=y, params=best_params)

        artifact = ModelArtifact(
            model=final_model,
            scaler=None,
            metadata=ModelMetadata(
                model_version=self._model_version,
                feature_names=FEATURE_NAMES,
                auc_mean=best_auc,
                auc_std=best_std,
                n_samples=len(sorted_samples),
                n_positives=dataset.positives,
                n_negatives=dataset.negatives,
                best_params=best_params,
                trained_at=datetime.now(UTC),
            ),
        )

        path = self._artifact_dir / f"anomaly_{self._model_version}.joblib"
        artifact.save(path)
        return TrainingReport(
            model_version=self._model_version,
            artifact_path=path,
            auc_mean=best_auc,
            auc_std=best_std,
            n_samples=len(sorted_samples),
            n_positives=dataset.positives,
            n_negatives=dataset.negatives,
            best_params=best_params,
        )

    def _hyperopt(
        self,
        *,
        x: Any,
        y: Any,
    ) -> tuple[dict[str, float | int], float, float]:
        """Itera el grid y devuelve el mejor por AUC media en CV."""
        best_params: dict[str, float | int] = {}
        best_mean: float = -1.0
        best_std: float = 0.0
        for params in self._grid:
            mean, std = self._cross_validate(x=x, y=y, params=params)
            if mean > best_mean:
                best_mean = mean
                best_std = std
                best_params = dict(params)
        return best_params, best_mean, best_std

    def _cross_validate(
        self,
        *,
        x: Any,
        y: Any,
        params: dict[str, float | int],
    ) -> tuple[float, float]:
        """5-fold time-series CV; devuelve (mean, std) del AUC."""
        import lightgbm as lgb
        import numpy as np
        from sklearn.metrics import roc_auc_score
        from sklearn.model_selection import TimeSeriesSplit

        splitter = TimeSeriesSplit(n_splits=self._n_splits)
        results: list[_FoldResult] = []
        for fold_idx, (train_idx, val_idx) in enumerate(splitter.split(x)):
            x_train, x_val = x[train_idx], x[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]
            if len(np.unique(y_val)) < 2 or len(np.unique(y_train)) < 2:
                continue
            model = self._build_booster(params=params)
            model.fit(
                x_train,
                y_train,
                eval_set=[(x_val, y_val)],
                callbacks=[lgb.early_stopping(self._early_stopping_rounds, verbose=False)],
            )
            preds = model.predict_proba(x_val)[:, 1]
            auc = float(roc_auc_score(y_val, preds))
            results.append(_FoldResult(fold=fold_idx, auc=auc))
        if not results:
            return 0.5, 0.0
        aucs = np.asarray([r.auc for r in results], dtype=np.float64)
        return float(aucs.mean()), float(aucs.std())

    def _fit_final(
        self,
        *,
        x: Any,
        y: Any,
        params: dict[str, float | int],
    ) -> Any:
        """Ajusta el modelo final sobre TODO el dataset con los mejores params.

        Devuelve un Booster (no el wrapper sklearn) para que la
        inferencia pueda usar ``pred_contrib=True`` directamente.
        """
        wrapper = self._build_booster(params=params)
        wrapper.fit(x, y)
        return wrapper.booster_

    def _build_booster(self, *, params: dict[str, float | int]) -> Any:
        """Construye un ``LGBMClassifier`` con el preset estable.

        ``params`` es un dict[str, float | int], pero ``LGBMClassifier``
        tiene firmas tipadas estrictas; el ``Any`` cast evita que mypy
        rechace la expansion ``**params``.
        """
        import lightgbm as lgb

        kwargs: dict[str, Any] = dict(params)
        return lgb.LGBMClassifier(
            objective="binary",
            class_weight="balanced",
            n_estimators=self._n_estimators,
            random_state=self._random_state,
            n_jobs=-1,
            verbose=-1,
            **kwargs,
        )

    @staticmethod
    def hyperopt_grid() -> tuple[dict[str, float | int], ...]:
        """Devuelve el grid actual (útil para inspección/tests)."""
        return _DEFAULT_GRID

    @staticmethod
    def _all_combinations(
        *,
        grid: dict[str, list[float | int]],
    ) -> list[dict[str, float | int]]:
        """Helper auxiliar para expandir un grid plano a combos."""
        keys = list(grid.keys())
        combos: list[dict[str, float | int]] = []
        for values in itertools.product(*(grid[k] for k in keys)):
            combos.append(dict(zip(keys, values, strict=True)))
        return combos
