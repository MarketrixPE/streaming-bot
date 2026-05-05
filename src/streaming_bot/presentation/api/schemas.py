"""Schemas Pydantic v2 para la API REST v1.

Los DTO viajan entre la capa HTTP y los handlers; nunca exponen modelos
SQLAlchemy ni entidades de dominio directamente. Todas las salidas usan
``model_config = ConfigDict(from_attributes=True)`` para poder serializar
desde dataclasses del dominio (Account, Song, Artist, etc.) sin tener
que reescribir mapeos manuales en cada ruta.

PaginatedResponse[T] es generico: cada router lo concreta con su DTO.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------
class ErrorResponse(BaseModel):
    """Respuesta uniforme para todos los errores HTTP.

    El campo ``request_id`` permite correlacionar con logs estructurados
    cuando el operador reporta un fallo.
    """

    model_config = ConfigDict(extra="forbid")

    error_code: str = Field(description="Codigo estable identificando el error")
    message: str = Field(description="Mensaje legible para humanos en es-ES")
    request_id: str = Field(description="UUID4 generado por RequestIdMiddleware")


# ---------------------------------------------------------------------------
# Paginacion
# ---------------------------------------------------------------------------
class PaginatedResponse(BaseModel, Generic[T]):
    """Envuelve una pagina de resultados cursor-based.

    ``next_cursor`` es opaco para el cliente: solo lo reenvia. ``total``
    es opcional porque calcularlo en tablas grandes es caro.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[T]
    limit: int = Field(ge=1, le=1000)
    next_cursor: str | None = None
    total: int | None = None


# ---------------------------------------------------------------------------
# DTOs del catalogo - tracks, artistas y labels
# ---------------------------------------------------------------------------
class TrackDTO(BaseModel):
    """Snapshot de una cancion del catalogo expuesta en el API."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    spotify_uri: str
    title: str
    artist_name: str
    artist_uri: str
    role: str
    duration_seconds: int
    isrc: str | None = None
    label: str | None = None
    distributor: str | None = None
    tier: str
    is_active: bool
    baseline_streams_per_day: float
    target_streams_per_day: int
    current_streams_today: int
    spike_oct2025_flag: bool
    primary_artist_id: str | None = None
    label_id: str | None = None


class ArtistDTO(BaseModel):
    """Artista (multi-artist support)."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    name: str
    spotify_uri: str | None = None
    primary_country: str | None = None
    label_id: str | None = None
    status: str
    has_spike_history: bool
    notes: str = ""
    created_at: datetime
    updated_at: datetime


class LabelDTO(BaseModel):
    """Sello / cuenta de distribuidor."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    name: str
    distributor: str
    distributor_account_id: str | None = None
    owner_email: str | None = None
    health: str
    last_health_check: datetime | None = None
    notes: str = ""
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Accounts / personas / health
# ---------------------------------------------------------------------------
class AccountDTO(BaseModel):
    """Cuenta listening del pool. Nunca expone password en claro."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    username: str
    country: str
    state: str
    state_reason: str | None = None
    last_used_at: datetime | None = None


class AccountHealthDTO(BaseModel):
    """Snapshot de salud operativa de la cuenta."""

    model_config = ConfigDict(extra="forbid")

    account_id: str
    state: str
    is_usable: bool
    last_used_at: datetime | None = None
    streams_today: int = 0
    notes: str | None = None


class FeatureContributionDTO(BaseModel):
    """Contribucion SHAP individual para explainability."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    feature_name: str
    contribution: float


class AnomalyScoreDTO(BaseModel):
    """Score de anomalia emitido por el predictor LightGBM."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    account_id: str
    score: float = Field(ge=0.0, le=1.0)
    risk_level: str
    computed_at: datetime
    top_features: list[FeatureContributionDTO] = Field(default_factory=list)
    model_version: str = "unknown"


# ---------------------------------------------------------------------------
# Jobs / sesiones
# ---------------------------------------------------------------------------
class JobDTO(BaseModel):
    """Una sesion ejecutada (modelo equivalente a 'job' en v1).

    En v1 unificamos el concepto de job y session: cada sesion del bot
    representa una unidad de trabajo concreta para una cuenta. Cuando
    introduzcamos el queue Temporal explicito en v2, anadimos un
    JobDTO independiente.
    """

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    session_id: str
    account_id: str
    started_at: datetime
    ended_at: datetime | None = None
    proxy_country: str | None = None
    user_agent: str | None = None
    target_streams_attempted: int
    camouflage_streams_attempted: int
    streams_counted: int
    skips: int
    likes_given: int
    saves_given: int
    follows_given: int
    error_class: str | None = None
    completed_normally: bool


# ---------------------------------------------------------------------------
# Metricas / observabilidad
# ---------------------------------------------------------------------------
class KpiSummaryDTO(BaseModel):
    """KPIs agregados para el dashboard de overview."""

    model_config = ConfigDict(extra="forbid")

    accounts_total: int
    accounts_active: int
    songs_total: int
    songs_active_targets: int
    artists_total: int
    labels_total: int
    sessions_today: int
    streams_counted_today: int


class StreamsByDspDTO(BaseModel):
    """Conteo de streams agrupado por DSP destino."""

    model_config = ConfigDict(extra="forbid")

    by_dsp: dict[str, int]
    window: Literal["today", "last_24h", "last_7d"] = "today"


class AnomalyAlertDTO(BaseModel):
    """Alerta activa de anomalia (cuenta en riesgo HIGH/CRITICAL)."""

    model_config = ConfigDict(extra="forbid")

    account_id: str
    username: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    risk_level: str
    reason: str | None = None
    detected_at: datetime


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
class TierAssignmentDTO(BaseModel):
    """Asignacion de tier para un track concreto."""

    model_config = ConfigDict(extra="forbid")

    track_id: str
    spotify_uri: str
    tier: str
    rationale: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    """Respuesta basica para /health y /readyz."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded", "starting"] = "ok"
    version: str = "v1"
    component_checks: dict[str, str] = Field(default_factory=dict)
