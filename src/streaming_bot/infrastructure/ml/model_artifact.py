"""Persistencia versionada del modelo entrenado.

El artefacto contiene:
- ``model``: Booster LightGBM (entrenado).
- ``scaler``: opcional ``StandardScaler`` de sklearn para normalizar.
- ``feature_names``: tupla de nombres en orden canónico (debe coincidir
  con ``FEATURE_NAMES`` del dominio).
- ``metadata``: versión semántica + AUC + fecha + params.

Joblib se usa por compatibilidad con sklearn estándar; los pickles son
compresivos (``compress=3``) y suficientes para artefactos < 50 MB.

Carga lazy: ``ModelArtifact.load`` es un classmethod estático que
importa joblib justo antes de tocar disco.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    """Metadata serializada junto al modelo."""

    model_version: str
    feature_names: tuple[str, ...]
    auc_mean: float
    auc_std: float
    n_samples: int
    n_positives: int
    n_negatives: int
    best_params: dict[str, float | int] = field(default_factory=dict)
    trained_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class ModelArtifact:
    """Wrapper sobre el modelo + scaler + metadata.

    ``model`` y ``scaler`` se tipan como ``Any`` porque LightGBM y
    sklearn no exponen tipos amigables; mantenerlos opacos al dominio
    minimiza acoplamiento.
    """

    model: Any
    scaler: Any | None
    metadata: ModelMetadata

    def save(self, path: Path) -> None:
        """Persiste el artefacto comprimido en disco."""
        import joblib

        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "model": self.model,
            "scaler": self.scaler,
            "metadata": self.metadata,
        }
        joblib.dump(payload, str(path), compress=3)

    @classmethod
    def load(cls, path: Path) -> ModelArtifact:
        """Carga artefacto previamente persistido."""
        import joblib

        if not path.exists():
            raise FileNotFoundError(f"artefacto inexistente: {path}")
        payload: dict[str, Any] = joblib.load(str(path))
        return cls(
            model=payload["model"],
            scaler=payload.get("scaler"),
            metadata=payload["metadata"],
        )
