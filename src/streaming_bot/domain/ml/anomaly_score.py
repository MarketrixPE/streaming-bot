"""Value object con el score de anomalía y nivel de riesgo asociado.

El predictor LightGBM emite un score continuo en [0,1] que representa la
probabilidad de baneo en las próximas 48h. Aquí lo envolvemos en un VO
inmutable para que el dominio razone sobre niveles discretos (LOW,
MEDIUM, HIGH, CRITICAL) sin depender de la implementación.

`top_features` se usa para explainability en el dashboard: SHAP devuelve
las top-3 features que mas empujaron la decisión, en formato
``(nombre_feature, contribucion)``. La contribución puede ser negativa
(empuja hacia "no banea") aunque normalmente solo se reportan positivas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class RiskLevel(str, Enum):
    """Nivel discreto de riesgo derivado del score continuo."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class FeatureContribution:
    """Contribución SHAP de una feature individual al score final."""

    feature_name: str
    contribution: float


@dataclass(frozen=True, slots=True)
class AnomalyScore:
    """Score de anomalía emitido por el predictor LightGBM.

    Reglas:
    - ``score`` debe estar en [0,1] (probabilidad calibrada).
    - ``risk_level`` se deriva determinísticamente del score con los
      umbrales por defecto. El servicio puede recomputar el nivel pasando
      thresholds custom via ``from_score``.
    - ``top_features`` expone hasta 3 contribuciones para explainability.
    - ``model_version`` permite rastrear qué artefacto generó el score.
    """

    account_id: str
    score: float
    risk_level: RiskLevel
    computed_at: datetime
    top_features: tuple[FeatureContribution, ...] = field(default_factory=tuple)
    model_version: str = "unknown"

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score fuera de rango [0,1]: {self.score}")
        if len(self.top_features) > 10:
            raise ValueError(
                f"top_features excede 10 entradas: {len(self.top_features)}",
            )

    @classmethod
    def from_score(
        cls,
        *,
        account_id: str,
        score: float,
        computed_at: datetime,
        top_features: tuple[FeatureContribution, ...] = (),
        model_version: str = "unknown",
        threshold_medium: float = 0.4,
        threshold_high: float = 0.7,
        threshold_critical: float = 0.85,
    ) -> AnomalyScore:
        """Construye un score derivando ``risk_level`` desde umbrales."""
        risk = _classify_risk(
            score=score,
            threshold_medium=threshold_medium,
            threshold_high=threshold_high,
            threshold_critical=threshold_critical,
        )
        return cls(
            account_id=account_id,
            score=score,
            risk_level=risk,
            computed_at=computed_at,
            top_features=top_features,
            model_version=model_version,
        )

    @property
    def is_actionable(self) -> bool:
        """True si el score es lo suficientemente alto para retirar la cuenta."""
        return self.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}


def _classify_risk(
    *,
    score: float,
    threshold_medium: float,
    threshold_high: float,
    threshold_critical: float,
) -> RiskLevel:
    """Mapea un score continuo a un ``RiskLevel`` discreto."""
    if score >= threshold_critical:
        return RiskLevel.CRITICAL
    if score >= threshold_high:
        return RiskLevel.HIGH
    if score >= threshold_medium:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW
