"""Use case que entrena el modelo periódicamente.

Pipeline:
1. Pull labeled data desde Postgres + ClickHouse (90 días por defecto).
2. Time-based split (no random) para evitar data leakage temporal.
3. Train LightGBM con CV (5 folds time-series) + hyperopt simple sobre
   ``num_leaves``, ``learning_rate``, ``min_data_in_leaf``, ``max_depth``.
4. Persistir artefacto versionado en disco (joblib) + metadata.

Este módulo NO importa LightGBM directamente; depende de los puertos
``ITrainingDataSource`` (extracción) y ``IModelTrainer`` (entrenamiento)
implementados en infraestructura.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from structlog.stdlib import BoundLogger

    from streaming_bot.domain.ml.feature_vector import AccountFeatureVector


@dataclass(frozen=True, slots=True)
class LabeledFeatureSample:
    """Una observación etiquetada para entrenamiento.

    ``label`` = 1 si la cuenta fue baneada en las próximas 48h tras
    ``observed_at``. ``observed_at`` se usa para ordenar el split temporal.
    """

    features: AccountFeatureVector
    label: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class TrainingDataset:
    """Conjunto de muestras a entrenar."""

    samples: tuple[LabeledFeatureSample, ...]
    window_start: datetime
    window_end: datetime

    @property
    def positives(self) -> int:
        return sum(1 for s in self.samples if s.label == 1)

    @property
    def negatives(self) -> int:
        return sum(1 for s in self.samples if s.label == 0)


@dataclass(frozen=True, slots=True)
class TrainingReport:
    """Métricas y metadata producidas por el trainer."""

    model_version: str
    artifact_path: Path
    auc_mean: float
    auc_std: float
    n_samples: int
    n_positives: int
    n_negatives: int
    best_params: dict[str, float | int] = field(default_factory=dict)
    trained_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class ITrainingDataSource(Protocol):
    """Fuente de datos etiquetados para entrenamiento."""

    async def fetch_labeled_window(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> TrainingDataset: ...


@runtime_checkable
class IModelTrainer(Protocol):
    """Trainer concreto (LightGBM en infra)."""

    def train(self, dataset: TrainingDataset) -> TrainingReport: ...


class TrainModelUseCase:
    """Orquestador del re-entrenamiento periódico."""

    def __init__(
        self,
        *,
        data_source: ITrainingDataSource,
        trainer: IModelTrainer,
        window_days: int = 90,
        logger: BoundLogger | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        if window_days <= 0:
            raise ValueError(f"window_days debe ser > 0: {window_days}")
        self._data_source = data_source
        self._trainer = trainer
        self._window_days = window_days
        self._logger = logger
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    async def execute(self) -> TrainingReport:
        """Ejecuta el pipeline completo: pull → train → persist."""
        end = self._now_factory()
        start = end - timedelta(days=self._window_days)
        if self._logger is not None:
            self._logger.info(
                "ml_training_started",
                window_start=start.isoformat(),
                window_end=end.isoformat(),
            )
        dataset = await self._data_source.fetch_labeled_window(
            window_start=start,
            window_end=end,
        )
        if dataset.positives == 0 or dataset.negatives == 0:
            raise ValueError(
                "dataset sin clases balanceadas (positives o negatives = 0)",
            )
        report = self._trainer.train(dataset)
        if self._logger is not None:
            self._logger.info(
                "ml_training_completed",
                model_version=report.model_version,
                auc_mean=report.auc_mean,
                auc_std=report.auc_std,
                n_samples=report.n_samples,
                artifact_path=str(report.artifact_path),
            )
        return report
