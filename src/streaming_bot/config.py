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
    mode: ProxyMode = ProxyMode.NONE
    file_path: Path = Path("./credentials/proxies.txt")
    healthcheck_url: str = "https://api.ipify.org"


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

    demo_url: str = "https://demo.playwright.dev/todomvc/"


def load_settings() -> Settings:
    """Factory para cargar settings. Útil para mockear en tests."""
    return Settings()
