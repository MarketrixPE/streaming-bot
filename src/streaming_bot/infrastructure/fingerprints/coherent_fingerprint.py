"""Generador de fingerprints coherentes IP↔TZ↔Geo↔Locale↔UA.

A diferencia del bot original que asignaba random.choice() a cada campo
INDEPENDIENTEMENTE (un proxy en EE.UU. con timezone Antarctica/Vostok y
locale ja-JP es una bandera roja inmediata), este generador correlaciona
todas las dimensiones a partir del país.
"""

from __future__ import annotations

import secrets

from streaming_bot.domain.ports.fingerprint import IFingerprintGenerator
from streaming_bot.domain.value_objects import (
    Country,
    Fingerprint,
    GeoCoordinate,
    ProxyEndpoint,
)

# User-Agents modernos (Chrome 130+, Firefox 130+, Safari 18). Refrescar trimestralmente.
_MODERN_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
)


# Tabla de coherencia: país → (timezone canónica, locale principal, ciudad capital)
_COUNTRY_PROFILES: dict[Country, tuple[str, str, GeoCoordinate]] = {
    Country.US: ("America/New_York", "en-US", GeoCoordinate(40.7128, -74.0060)),
    Country.GB: ("Europe/London", "en-GB", GeoCoordinate(51.5074, -0.1278)),
    Country.DE: ("Europe/Berlin", "de-DE", GeoCoordinate(52.5200, 13.4050)),
    Country.FR: ("Europe/Paris", "fr-FR", GeoCoordinate(48.8566, 2.3522)),
    Country.ES: ("Europe/Madrid", "es-ES", GeoCoordinate(40.4168, -3.7038)),
    Country.IT: ("Europe/Rome", "it-IT", GeoCoordinate(41.9028, 12.4964)),
    Country.BR: ("America/Sao_Paulo", "pt-BR", GeoCoordinate(-23.5505, -46.6333)),
    Country.MX: ("America/Mexico_City", "es-MX", GeoCoordinate(19.4326, -99.1332)),
    Country.AR: ("America/Argentina/Buenos_Aires", "es-AR", GeoCoordinate(-34.6037, -58.3816)),
    Country.JP: ("Asia/Tokyo", "ja-JP", GeoCoordinate(35.6762, 139.6503)),
}


def _jitter(coord: GeoCoordinate, *, radius_km: float = 5.0) -> GeoCoordinate:
    """Añade ruido de ~5km a una coordenada para que dos cuentas no coincidan exactamente.

    1° latitud ≈ 111 km, 1° longitud ≈ 111 * cos(lat) km. Aproximación suficiente
    para nuestro propósito (no es navegación aérea).
    """
    delta_lat = (secrets.randbelow(2000) - 1000) / 1000 * (radius_km / 111.0)
    delta_lon = (secrets.randbelow(2000) - 1000) / 1000 * (radius_km / 111.0)
    return GeoCoordinate(
        latitude=max(-90.0, min(90.0, coord.latitude + delta_lat)),
        longitude=max(-180.0, min(180.0, coord.longitude + delta_lon)),
    )


class CoherentFingerprintGenerator(IFingerprintGenerator):
    """Implementación por defecto: tabla estática + jitter geográfico."""

    def __init__(
        self,
        *,
        viewport_width: int = 1366,
        viewport_height: int = 768,
    ) -> None:
        self._viewport_width = viewport_width
        self._viewport_height = viewport_height

    def coherent_for(
        self,
        proxy: ProxyEndpoint | None,
        *,
        fallback_country: Country = Country.US,
    ) -> Fingerprint:
        country = proxy.country if proxy and proxy.country else fallback_country
        timezone_id, locale, capital = _COUNTRY_PROFILES.get(
            country,
            _COUNTRY_PROFILES[Country.US],
        )
        return Fingerprint(
            user_agent=secrets.choice(_MODERN_USER_AGENTS),
            locale=locale,
            timezone_id=timezone_id,
            geolocation=_jitter(capital),
            country=country,
            viewport_width=self._viewport_width,
            viewport_height=self._viewport_height,
        )
