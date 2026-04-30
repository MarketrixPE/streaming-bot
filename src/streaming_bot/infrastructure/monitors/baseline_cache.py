"""Cache de baselines historicas para deteccion de caidas anomalas.

Persiste metricas (streams, earnings, listeners) por plataforma y permite
calcular el delta porcentual respecto a la mediana de las ultimas N muestras.

Implementacion: JSON file local con un dict anidado:

    {
        "distrokid": {
            "earnings": [
                {"value": 123.45, "when": "2025-01-31T00:00:00+00:00"},
                ...
            ]
        }
    }

El cache es ``async`` solo en la firma para poder ser mockeado uniformemente
con los monitors; la I/O subyacente es sincrona (archivo pequeno, no es
cuello de botella).
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from structlog.stdlib import BoundLogger

from streaming_bot.domain.ports.distributor_monitor import DistributorPlatform


@dataclass(frozen=True, slots=True)
class BaselineSample:
    """Punto historico de una metrica."""

    value: float
    when: datetime

    def as_dict(self) -> dict[str, float | str]:
        return {"value": self.value, "when": self.when.isoformat()}

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> BaselineSample:
        when_raw = raw.get("when")
        value_raw = raw.get("value")
        if not isinstance(when_raw, str) or not isinstance(value_raw, (int, float)):
            raise ValueError(f"BaselineSample malformado: {raw!r}")
        return cls(value=float(value_raw), when=datetime.fromisoformat(when_raw))


class BaselineCache:
    """Cache JSON en disco para historicos de metricas por plataforma.

    Args:
        cache_path: ruta del JSON. Se crea si no existe.
        max_samples_per_metric: tope para evitar crecimiento ilimitado.
        logger: logger structlog.
    """

    def __init__(
        self,
        *,
        cache_path: Path,
        max_samples_per_metric: int = 36,
        logger: BoundLogger,
    ) -> None:
        self._cache_path = cache_path
        self._max_samples = max_samples_per_metric
        self._logger = logger.bind(component="baseline_cache")
        self._lock = Lock()
        self._data: dict[str, dict[str, list[BaselineSample]]] = {}
        self._load()

    # ── Persistencia ─────────────────────────────────────────────────────────
    def _load(self) -> None:
        if not self._cache_path.exists():
            self._data = {}
            return
        try:
            with self._cache_path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            self._logger.warning("baseline_load_failed", error=str(exc))
            self._data = {}
            return

        parsed: dict[str, dict[str, list[BaselineSample]]] = {}
        for platform, metrics in raw.items():
            if not isinstance(metrics, dict):
                continue
            parsed[platform] = {}
            for metric_name, samples in metrics.items():
                if not isinstance(samples, list):
                    continue
                parsed_samples: list[BaselineSample] = []
                for s in samples:
                    if not isinstance(s, dict):
                        continue
                    try:
                        parsed_samples.append(BaselineSample.from_dict(s))
                    except (ValueError, TypeError):
                        continue
                parsed[platform][metric_name] = parsed_samples
        self._data = parsed

    def _persist(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        serializable: dict[str, dict[str, list[dict[str, float | str]]]] = {}
        for platform, metrics in self._data.items():
            serializable[platform] = {}
            for metric_name, samples in metrics.items():
                serializable[platform][metric_name] = [s.as_dict() for s in samples]
        try:
            with self._cache_path.open("w", encoding="utf-8") as fh:
                json.dump(serializable, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            self._logger.warning("baseline_persist_failed", error=str(exc))

    # ── API publica ──────────────────────────────────────────────────────────
    def record_metric(
        self,
        platform: DistributorPlatform,
        metric_name: str,
        value: float,
        when: datetime | None = None,
    ) -> None:
        """Registra una nueva muestra. Hace truncado FIFO al ``max_samples``."""
        sample_when = when or datetime.now(UTC)
        with self._lock:
            metrics = self._data.setdefault(platform.value, {})
            samples = metrics.setdefault(metric_name, [])
            samples.append(BaselineSample(value=value, when=sample_when))
            if len(samples) > self._max_samples:
                # Conservamos las muestras mas recientes.
                samples_sorted = sorted(samples, key=lambda s: s.when)
                metrics[metric_name] = samples_sorted[-self._max_samples :]
            self._persist()

    def get_recent(
        self,
        platform: DistributorPlatform,
        metric_name: str,
        last_n: int = 12,
    ) -> list[BaselineSample]:
        """Devuelve las ultimas ``last_n`` muestras (mas reciente al final)."""
        with self._lock:
            samples = self._data.get(platform.value, {}).get(metric_name, [])
            ordered = sorted(samples, key=lambda s: s.when)
            return ordered[-last_n:]

    def compute_delta_pct(
        self,
        platform: DistributorPlatform,
        metric_name: str,
        current_value: float,
        baseline_window: int = 6,
    ) -> float | None:
        """Calcula ``(current - baseline) / baseline * 100`` usando la mediana
        de las ultimas ``baseline_window`` muestras como baseline.

        Devuelve ``None`` si no hay historico suficiente (>=1 muestra).
        """
        recent = self.get_recent(platform, metric_name, last_n=baseline_window)
        if not recent:
            return None
        baseline = statistics.median(s.value for s in recent)
        if baseline == 0:
            return None
        return ((current_value - baseline) / baseline) * 100.0

    def reset_metric(self, platform: DistributorPlatform, metric_name: str) -> None:
        """Elimina el historico de una metrica. Util tras una rotacion de cuenta."""
        with self._lock:
            metrics = self._data.get(platform.value, {})
            metrics.pop(metric_name, None)
            self._persist()
