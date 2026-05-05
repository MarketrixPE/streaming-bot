"""Feature vector usado por el predictor de anomalías.

Las features se calculan en `application/ml/feature_extractor.py` cruzando:
- Postgres (StreamHistory + SessionRecord para historial granular).
- ClickHouse (events.stream_events + events.account_health_snapshots para
  rollups y métricas de bajo coste).

El VO es inmutable y serializable a `numpy.ndarray` mediante `as_array()`
para alimentar a LightGBM. El orden de las features es CRÍTICO: debe
coincidir con `FEATURE_NAMES` para que el modelo no se confunda al
inferir. Cualquier cambio aquí obliga a re-entrenar.

Convenciones:
- `*_24h` cubren las últimas 24 horas hasta `computed_at`.
- `*_7d` cubren los últimos 7 días.
- `save_rate`, `skip_rate`, `queue_rate` son ratios en [0,1].
- `*_consistency*` son scores en [0,1] (1 = totalmente consistente).
- counts UInt como float para tener un único dtype hacia LightGBM.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

FEATURE_NAMES: tuple[str, ...] = (
    "streams_24h",
    "streams_7d",
    "save_rate_24h",
    "skip_rate_24h",
    "queue_rate_24h",
    "ip_diversity_24h",
    "fingerprint_age_days",
    "distinct_dsps_24h",
    "hour_of_day_consistency",
    "geo_consistency_score",
    "captcha_encounters_24h",
    "failed_streams_24h",
    "partial_streams_24h",
    "completion_rate_24h",
    "sessions_24h",
    "avg_session_duration_minutes",
    "distinct_artists_24h",
    "distinct_tracks_24h",
    "repeat_track_ratio_24h",
    "night_streams_ratio_24h",
    "rapid_skip_ratio_24h",
    "country_changes_24h",
    "user_agent_changes_7d",
    "previous_quarantine_count_30d",
)
"""Orden canonico de features. Debe coincidir con el orden del modelo."""


@dataclass(frozen=True, slots=True)
class AccountFeatureVector:
    """Vector de features de una cuenta en un instante temporal.

    Inmutable para evitar mutaciones accidentales entre extracción e
    inferencia. Convertir a array via ``as_array`` antes de llamar al
    modelo. Construir via ``from_dict`` cuando los datos vengan de un
    diccionario heterogéneo (ej. respuesta JSON de ClickHouse).
    """

    account_id: str
    streams_24h: float
    streams_7d: float
    save_rate_24h: float
    skip_rate_24h: float
    queue_rate_24h: float
    ip_diversity_24h: float
    fingerprint_age_days: float
    distinct_dsps_24h: float
    hour_of_day_consistency: float
    geo_consistency_score: float
    captcha_encounters_24h: float
    failed_streams_24h: float
    partial_streams_24h: float
    completion_rate_24h: float
    sessions_24h: float
    avg_session_duration_minutes: float
    distinct_artists_24h: float
    distinct_tracks_24h: float
    repeat_track_ratio_24h: float
    night_streams_ratio_24h: float
    rapid_skip_ratio_24h: float
    country_changes_24h: float
    user_agent_changes_7d: float
    previous_quarantine_count_30d: float

    def __post_init__(self) -> None:
        for name in (
            "save_rate_24h",
            "skip_rate_24h",
            "queue_rate_24h",
            "completion_rate_24h",
            "hour_of_day_consistency",
            "geo_consistency_score",
            "repeat_track_ratio_24h",
            "night_streams_ratio_24h",
            "rapid_skip_ratio_24h",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} fuera de rango [0,1]: {value}")
        for name in (
            "streams_24h",
            "streams_7d",
            "ip_diversity_24h",
            "fingerprint_age_days",
            "distinct_dsps_24h",
            "captcha_encounters_24h",
            "failed_streams_24h",
            "partial_streams_24h",
            "sessions_24h",
            "avg_session_duration_minutes",
            "distinct_artists_24h",
            "distinct_tracks_24h",
            "country_changes_24h",
            "user_agent_changes_7d",
            "previous_quarantine_count_30d",
        ):
            value = getattr(self, name)
            if value < 0.0:
                raise ValueError(f"{name} no puede ser negativo: {value}")

    def as_array(self) -> list[float]:
        """Devuelve los valores numéricos en el orden de ``FEATURE_NAMES``.

        Usamos ``list[float]`` en vez de ``numpy.ndarray`` para no
        introducir dependencias pesadas en el dominio. La infra es la
        responsable de envolverlo en ``np.asarray`` antes de pasar al
        modelo.
        """
        return [float(getattr(self, name)) for name in FEATURE_NAMES]

    def as_dict(self) -> dict[str, float | str]:
        """Diccionario legible (usado por logs y tests)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, *, account_id: str, values: dict[str, float]) -> AccountFeatureVector:
        """Construye desde dict; rellena con 0.0 las features ausentes.

        Esta tolerancia permite evolucionar el extractor de features sin
        romper deserialización legacy. Logs aguas arriba deben avisar de
        las features ausentes para investigar gaps en ClickHouse.
        """
        kwargs = {name: float(values.get(name, 0.0)) for name in FEATURE_NAMES}
        return cls(account_id=account_id, **kwargs)
