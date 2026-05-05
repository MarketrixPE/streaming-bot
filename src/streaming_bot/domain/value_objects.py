"""Value objects inmutables del dominio.

Reglas:
- Inmutables (frozen).
- Validan invariantes en construcción.
- Sin lógica de I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Country(str, Enum):
    """ISO 3166-1 alpha-2. Cobertura objetivo: LATAM full + EU/UK + US.

    Estrategia post-Oct'25: priorizar LATAM (PE, MX, US-hispano, ES, CL, AR, CO,
    EC, BO, DO) durante 90 dias de cooling-off. UK/CH se reintroducen
    gradualmente despues del periodo.
    """

    # Latinoamerica
    PE = "PE"  # Peru: mercado dominante actual (6.6k/mes organico)
    MX = "MX"  # Mexico: segundo mercado LATAM
    US = "US"  # USA: hispano + global
    CL = "CL"  # Chile
    AR = "AR"  # Argentina
    CO = "CO"  # Colombia
    EC = "EC"  # Ecuador
    BO = "BO"  # Bolivia
    DO = "DO"  # Republica Dominicana
    PR = "PR"  # Puerto Rico
    VE = "VE"  # Venezuela
    UY = "UY"  # Uruguay
    PY = "PY"  # Paraguay
    PA = "PA"  # Panama
    GT = "GT"  # Guatemala
    HN = "HN"  # Honduras
    SV = "SV"  # El Salvador
    NI = "NI"  # Nicaragua
    CR = "CR"  # Costa Rica
    BR = "BR"  # Brasil

    # Europa (cooling-off Q2 2026, reintroducir Q3 con curva organica)
    ES = "ES"  # Espana
    GB = "GB"  # Reino Unido (PAUSA: huella de boost previo)
    CH = "CH"  # Suiza (PAUSA: huella critica de boost previo)
    DE = "DE"
    FR = "FR"
    IT = "IT"
    PT = "PT"
    NL = "NL"
    SE = "SE"
    NO = "NO"
    DK = "DK"
    FI = "FI"
    IE = "IE"
    AT = "AT"
    BE = "BE"

    # Asia/Oceania
    JP = "JP"
    AU = "AU"
    NZ = "NZ"
    # Asia: mercados objetivo Q2 2026 (router asiatico: JioSaavn / KKBox / NetEase).
    IN = "IN"  # India: mercado de volumen (JioSaavn)
    TW = "TW"  # Taiwan (KKBox)
    HK = "HK"  # Hong Kong (KKBox)
    CN = "CN"  # China continental (NetEase, requiere proxy CN)
    KR = "KR"  # Corea del Sur (KKBox fallback)

    # Otros
    CA = "CA"
    TH = "TH"


@dataclass(frozen=True, slots=True)
class GeoCoordinate:
    """Coordenada geográfica WGS84."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError(f"latitude fuera de rango: {self.latitude}")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError(f"longitude fuera de rango: {self.longitude}")


@dataclass(frozen=True, slots=True)
class ProxyEndpoint:
    """Endpoint de proxy HTTP/SOCKS."""

    scheme: str  # http | https | socks5
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    country: Country | None = None

    def __post_init__(self) -> None:
        if self.scheme not in {"http", "https", "socks5"}:
            raise ValueError(f"scheme inválido: {self.scheme}")
        if not 1 <= self.port <= 65535:
            raise ValueError(f"port fuera de rango: {self.port}")

    def as_url(self) -> str:
        """Devuelve la URL en formato Playwright (sin credenciales embebidas)."""
        return f"{self.scheme}://{self.host}:{self.port}"


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """Huella coherente que el browser debe presentar.

    Coherencia: country ↔ timezone ↔ locale ↔ geolocation ↔ user_agent.
    Construido por IFingerprintGenerator.coherent_for(proxy).
    """

    user_agent: str
    locale: str  # e.g. "es-ES"
    timezone_id: str  # e.g. "Europe/Madrid"
    geolocation: GeoCoordinate
    country: Country
    viewport_width: int = 1366
    viewport_height: int = 768

    def realistic_listen_seconds(self) -> int:
        """Duración 'humana' realista para una escucha (placeholder).

        En un caso real se modela como muestra de una distribución
        log-normal centrada en ~180s con varianza por género/cuenta.
        """
        return 35  # mínimo de Spotify para contar como stream válido


@dataclass(frozen=True, slots=True)
class StreamResult:
    """Resultado de un job de streaming. Tagged union estilo Result<T,E>."""

    success: bool
    account_id: str
    duration_ms: int
    error_message: str | None = None
    artifacts_path: str | None = None

    @classmethod
    def ok(cls, *, account_id: str, duration_ms: int) -> StreamResult:
        return cls(success=True, account_id=account_id, duration_ms=duration_ms)

    @classmethod
    def failed(
        cls,
        *,
        account_id: str,
        duration_ms: int,
        error: str,
        artifacts_path: str | None = None,
    ) -> StreamResult:
        return cls(
            success=False,
            account_id=account_id,
            duration_ms=duration_ms,
            error_message=error,
            artifacts_path=artifacts_path,
        )
