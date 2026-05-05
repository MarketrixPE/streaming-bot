"""Configuración 12-factor con pydantic-settings.

Carga prioridad:
1. Variables de entorno con prefijo SB_ (uppercase)
2. Archivo .env en la raíz del proyecto
3. Defaults definidos aquí
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from streaming_bot.domain.value_objects import Country


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogFormat(str, Enum):
    JSON = "json"
    CONSOLE = "console"


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ProxyMode(str, Enum):
    NONE = "none"
    STATIC_FILE = "static_file"
    PROVIDER_API = "provider_api"


class BrowserSettings(BaseModel):
    headless: bool = True
    slow_mo_ms: int = 0
    default_timeout_ms: int = 30_000
    viewport_width: int = 1366
    viewport_height: int = 768


class StorageSettings(BaseModel):
    accounts_path: Path = Path("./credentials/accounts.encrypted")
    sessions_dir: Path = Path("./sessions")
    artifacts_dir: Path = Path("./artifacts")
    master_key: str = Field(default="", description="Clave maestra Fernet (base64)")


class ProxySettings(BaseModel):
    """Configuracion del proxy provider.

    Modos:
    - NONE: direct, sin proxy. Solo desarrollo / tests.
    - STATIC_FILE: lee proxies de un archivo (file_path).
    - PROVIDER_API: consulta API REST de un proveedor (Bright Data, Oxylabs,
        Smartproxy, IPRoyal, ProxyEmpire, NetNut, SOAX, etc.).
    """

    mode: ProxyMode = ProxyMode.NONE
    file_path: Path = Path("./credentials/proxies.txt")
    healthcheck_url: str = "https://api.ipify.org"

    # Settings PROVIDER_API. Solo se usan si mode == PROVIDER_API.
    api_endpoint: str = ""
    api_auth_header: str = ""
    api_auth_value: str = ""
    api_response_path: str = ""
    api_default_scheme: str = "http"
    api_cost_per_request_cents: float = 0.05
    api_cache_ttl_seconds: int = 600
    api_quarantine_seconds: int = 300
    api_max_pool_size_per_country: int = 50
    api_request_timeout_seconds: float = 10.0


class ObservabilitySettings(BaseModel):
    log_format: LogFormat = LogFormat.CONSOLE
    log_level: LogLevel = LogLevel.INFO
    metrics_enabled: bool = True
    metrics_port: int = 9090


class DatabaseSettings(BaseModel):
    """Configuración de la base de datos.

    URL ejemplos:
    - postgresql+asyncpg://user:pass@localhost:5432/streaming_bot
    - sqlite+aiosqlite:///./data/streaming_bot.db (dev/local)
    - sqlite+aiosqlite:///:memory: (tests)
    """

    url: str = "sqlite+aiosqlite:///./data/streaming_bot.db"
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 20


class DashboardSettings(BaseModel):
    """Flags y rutas del dashboard operacional."""

    flags_path: Path = Path("./data/dashboard_flags.json")
    panic_kill_switch_path: Path = Path("./data/panic.lock")


class SpotifyApiSettings(BaseModel):
    """Configuracion de credenciales Spotify Web API."""

    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = "http://127.0.0.1:8765/callback"
    user_refresh_token: str | None = None
    owner_user_id: str = ""
    default_market: Country = Country.PE


class AccountsApiSettings(BaseModel):
    """Configuracion de servicios externos para creacion de cuentas."""

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    mail_tm_base_url: str = "https://api.mail.tm"
    use_stub_sms: bool = True


class CaptchaProvider(str, Enum):
    """Providers de CAPTCHA disponibles para el router."""

    CAPSOLVER = "capsolver"
    TWOCAPTCHA = "twocaptcha"
    GPT4V = "gpt4v"


class CaptchaSettings(BaseModel):
    """Configuracion del stack CAPTCHA solver.

    El router intenta los providers en `provider_order` con failover y suma
    los costes estimados al `BudgetGuard` (cap diario en `daily_budget_cents`).
    Cuando el cap se rebasa, las llamadas siguientes se rechazan hasta el
    proximo dia UTC.
    """

    capsolver_api_key: str = ""
    twocaptcha_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    daily_budget_cents: float = Field(
        default=2000.0,
        ge=0.0,
        description="Cap diario acumulado en cents (USD * 100).",
    )

    provider_order: tuple[CaptchaProvider, ...] = (
        CaptchaProvider.CAPSOLVER,
        CaptchaProvider.TWOCAPTCHA,
        CaptchaProvider.GPT4V,
    )

    poll_interval_seconds: float = Field(default=3.0, gt=0.0)
    request_timeout_seconds: float = Field(default=30.0, gt=0.0)
    solve_timeout_seconds: float = Field(default=180.0, gt=0.0)

    gpt4v_model: str = "gpt-4o"
    anthropic_model: str = "claude-sonnet-4-5"


class DistributionSettings(BaseModel):
    """Configuracion del Multi-Distributor Dispatcher v1.

    Aglutina credenciales por distribuidor y selectores defensivos para los
    flows scrape (DistroKid). Las API keys / passwords se cargan via env vars
    con prefijo SB_DISTRIBUTION__ (ej. SB_DISTRIBUTION__DISTROKID_EMAIL).
    """

    label_name: str = "Worldwide Hits"
    min_distributors: int = Field(default=2, ge=1)
    max_concentration_pct: float = Field(default=0.25, gt=0.0, le=1.0)
    retry_takedown_threshold: int = Field(default=2, ge=1)

    # DistroKid (scrape via Patchright)
    distrokid_email: str = ""
    distrokid_password: str = ""
    distrokid_action_timeout_ms: int = Field(default=60_000, ge=1_000)
    distrokid_selector_upload_files: str = "[data-testid=upload-files]"
    distrokid_selector_track_title: str = "[data-testid=track-title]"
    distrokid_selector_artist_name: str = "[data-testid=artist-name]"
    distrokid_selector_label_name: str = "[data-testid=label-name]"
    distrokid_selector_isrc_input: str = "[data-testid=isrc-input]"
    distrokid_selector_submit_release: str = "[data-testid=submit-release]"
    distrokid_selector_confirmation: str = "[data-testid=release-confirmation]"
    distrokid_selector_captcha: str = "[data-testid=captcha]"

    # RouteNote (HTTP REST con cookies de session)
    routenote_email: str = ""
    routenote_password: str = ""
    routenote_base_url: str = "https://routenote.com"
    routenote_request_timeout_seconds: float = Field(default=30.0, gt=0.0)


class MLSettings(BaseModel):
    """Configuracion del subsistema de Machine Learning.

    - ``model_path``: ruta al artefacto joblib serializado.
    - ``threshold_quarantine_score`` / ``threshold_critical_score``:
      puntos de corte para emitir señales de cuarentena.
    - ``retrain_interval_hours``: cadencia del job que dispara el use
      case de re-entrenamiento (Temporal cron).
    - ``cache_ttl_seconds``: TTL en segundos del cache in-memory de
      predicciones por cuenta.
    - ``training_window_days``: ventana de datos que el trainer consume.
    - ``clickhouse_url``: HTTP interface de ClickHouse para queries de
      features.
    """

    model_path: Path = Path("./data/ml/models/anomaly_v0.1.0.joblib")
    threshold_quarantine_score: float = Field(default=0.7, ge=0.0, le=1.0)
    threshold_critical_score: float = Field(default=0.85, ge=0.0, le=1.0)
    retrain_interval_hours: int = Field(default=24, ge=1)
    cache_ttl_seconds: float = Field(default=1800.0, ge=0.0)
    training_window_days: int = Field(default=90, ge=7)
    clickhouse_url: str = "http://localhost:8123"
    clickhouse_database: str = "events"


class MasteringProfileName(str, Enum):
    """Nombre del perfil de masterizado por DSP objetivo."""

    SPOTIFY = "spotify"
    APPLE_MUSIC = "apple_music"
    PODCAST = "podcast"


class CatalogPipelineSettings(BaseModel):
    """Configuracion del pipeline de produccion de catalogo AI.

    Contiene credenciales de los proveedores externos (Suno, Udio, OpenAI),
    parametros operacionales (concurrencia, budget cap) y rutas locales.
    """

    suno_api_key: str = ""
    suno_base_url: str = "https://studio-api.suno.ai"

    udio_api_key: str = ""
    udio_base_url: str = "https://api.udio.com"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com"
    metadata_model: str = "gpt-4o-mini"
    cover_model: str = "dall-e-3"
    cover_size: str = "1024x1024"
    cover_quality: str = "hd"

    ffmpeg_path: Path = Path("/usr/local/bin/ffmpeg")
    raw_audio_dir: Path = Path("./data/raw_audio")
    mastered_audio_dir: Path = Path("./data/mastered_audio")
    cover_art_dir: Path = Path("./data/cover_art")

    mastering_profile: MasteringProfileName = MasteringProfileName.SPOTIFY

    max_concurrency: int = Field(default=4, ge=1, le=64)
    cost_per_track_cents: float = Field(default=15.0, ge=0.0)
    monthly_budget_cents: float = Field(default=7500.0, ge=0.0)


class ApiSettings(BaseModel):
    """Configuracion de la API REST FastAPI v1.

    Variables de entorno (prefijo SB_API__):
    - host / port: bind del servidor uvicorn (default 0.0.0.0:8000).
    - jwt_jwks_url: URL JWKS publicada por Better Auth para validar tokens.
    - jwt_audience / jwt_issuer: validados si vienen no vacios.
    - jwt_jwks_ttl_seconds: TTL del cache de JWKS (default 1h).
    - rate_limit_per_minute: tope para usuarios autenticados.
    - anonymous_rate_limit_per_minute: tope para clientes sin token.
    - allowed_origins: lista CORS para el dashboard Next.js.
    - docs_enabled: expone /docs y /redoc cuando es True.
    - request_id_header: nombre del header para el request id.
    """

    host: str = "0.0.0.0"  # noqa: S104 - escucha en todas las interfaces de la red interna
    port: int = Field(default=8000, ge=1, le=65535)

    jwt_jwks_url: str = "http://localhost:3000/api/auth/jwks"
    jwt_audience: str = ""
    jwt_issuer: str = ""
    jwt_algorithms: tuple[str, ...] = ("RS256",)
    jwt_jwks_ttl_seconds: int = Field(default=3600, ge=1)

    rate_limit_per_minute: int = Field(default=120, ge=1)
    anonymous_rate_limit_per_minute: int = Field(default=30, ge=1)

    allowed_origins: tuple[str, ...] = ("http://localhost:3000",)
    docs_enabled: bool = True
    request_id_header: str = "X-Request-ID"

    pagination_default_limit: int = Field(default=50, ge=1, le=1000)
    pagination_max_limit: int = Field(default=200, ge=1, le=1000)


class Settings(BaseSettings):
    """Configuración global. Inmutable en runtime."""

    model_config = SettingsConfigDict(
        env_prefix="SB_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    env: Environment = Environment.DEVELOPMENT

    concurrency: int = Field(default=10, ge=1, le=500)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_seconds: float = Field(default=2.0, ge=0.0)

    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    proxy: ProxySettings = Field(default_factory=ProxySettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    spotify: SpotifyApiSettings = Field(default_factory=SpotifyApiSettings)
    accounts: AccountsApiSettings = Field(default_factory=AccountsApiSettings)
    captcha: CaptchaSettings = Field(default_factory=CaptchaSettings)
    distribution: DistributionSettings = Field(default_factory=DistributionSettings)
    ml: MLSettings = Field(default_factory=MLSettings)
    catalog_pipeline: CatalogPipelineSettings = Field(default_factory=CatalogPipelineSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)

    demo_url: str = "https://demo.playwright.dev/todomvc/"


def load_settings() -> Settings:
    """Factory para cargar settings. Útil para mockear en tests."""
    return Settings()
