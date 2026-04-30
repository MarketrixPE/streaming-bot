"""Generador de fingerprints coherentes basado en Browserforge.

A diferencia del `CoherentFingerprintGenerator` (tabla estática + UA hardcoded),
este generador delega la creación del User-Agent y demás campos navigator/screen
a Browserforge, que cuenta con un dataset estadístico actualizado de fingerprints
reales. La coherencia geográfica (país↔TZ↔geo↔locale) se conserva mediante una
tabla local `Country -> (timezone, locale, capital)`.
"""

from __future__ import annotations

import secrets
from random import Random
from typing import Final

from browserforge.fingerprints import FingerprintGenerator as _BFGenerator

from streaming_bot.domain.ports.fingerprint import IFingerprintGenerator
from streaming_bot.domain.value_objects import (
    Country,
    Fingerprint,
    GeoCoordinate,
    ProxyEndpoint,
)

# Tabla de coherencia geográfica para todos los países que cubre el dominio.
# Coordenadas de la capital (o ciudad principal) y locale por defecto.
_COUNTRY_PROFILES: Final[dict[Country, tuple[str, str, GeoCoordinate]]] = {
    # Latinoamérica
    Country.PE: ("America/Lima", "es-PE", GeoCoordinate(-12.0464, -77.0428)),
    Country.MX: ("America/Mexico_City", "es-MX", GeoCoordinate(19.4326, -99.1332)),
    Country.US: ("America/New_York", "en-US", GeoCoordinate(40.7128, -74.0060)),
    Country.CL: ("America/Santiago", "es-CL", GeoCoordinate(-33.4489, -70.6693)),
    Country.AR: ("America/Argentina/Buenos_Aires", "es-AR", GeoCoordinate(-34.6037, -58.3816)),
    Country.CO: ("America/Bogota", "es-CO", GeoCoordinate(4.7110, -74.0721)),
    Country.EC: ("America/Guayaquil", "es-EC", GeoCoordinate(-0.1807, -78.4678)),
    Country.BO: ("America/La_Paz", "es-BO", GeoCoordinate(-16.5000, -68.1500)),
    Country.DO: ("America/Santo_Domingo", "es-DO", GeoCoordinate(18.4861, -69.9312)),
    Country.PR: ("America/Puerto_Rico", "es-PR", GeoCoordinate(18.4655, -66.1057)),
    Country.VE: ("America/Caracas", "es-VE", GeoCoordinate(10.4806, -66.9036)),
    Country.UY: ("America/Montevideo", "es-UY", GeoCoordinate(-34.9011, -56.1645)),
    Country.PY: ("America/Asuncion", "es-PY", GeoCoordinate(-25.2637, -57.5759)),
    Country.PA: ("America/Panama", "es-PA", GeoCoordinate(8.9824, -79.5199)),
    Country.GT: ("America/Guatemala", "es-GT", GeoCoordinate(14.6349, -90.5069)),
    Country.HN: ("America/Tegucigalpa", "es-HN", GeoCoordinate(14.0723, -87.1921)),
    Country.SV: ("America/El_Salvador", "es-SV", GeoCoordinate(13.6929, -89.2182)),
    Country.NI: ("America/Managua", "es-NI", GeoCoordinate(12.1149, -86.2362)),
    Country.CR: ("America/Costa_Rica", "es-CR", GeoCoordinate(9.9281, -84.0907)),
    Country.BR: ("America/Sao_Paulo", "pt-BR", GeoCoordinate(-23.5505, -46.6333)),
    # Europa
    Country.ES: ("Europe/Madrid", "es-ES", GeoCoordinate(40.4168, -3.7038)),
    Country.GB: ("Europe/London", "en-GB", GeoCoordinate(51.5074, -0.1278)),
    Country.CH: ("Europe/Zurich", "de-CH", GeoCoordinate(47.3769, 8.5417)),
    Country.DE: ("Europe/Berlin", "de-DE", GeoCoordinate(52.5200, 13.4050)),
    Country.FR: ("Europe/Paris", "fr-FR", GeoCoordinate(48.8566, 2.3522)),
    Country.IT: ("Europe/Rome", "it-IT", GeoCoordinate(41.9028, 12.4964)),
    Country.PT: ("Europe/Lisbon", "pt-PT", GeoCoordinate(38.7223, -9.1393)),
    Country.NL: ("Europe/Amsterdam", "nl-NL", GeoCoordinate(52.3676, 4.9041)),
    Country.SE: ("Europe/Stockholm", "sv-SE", GeoCoordinate(59.3293, 18.0686)),
    Country.NO: ("Europe/Oslo", "nb-NO", GeoCoordinate(59.9139, 10.7522)),
    Country.DK: ("Europe/Copenhagen", "da-DK", GeoCoordinate(55.6761, 12.5683)),
    Country.FI: ("Europe/Helsinki", "fi-FI", GeoCoordinate(60.1699, 24.9384)),
    Country.IE: ("Europe/Dublin", "en-IE", GeoCoordinate(53.3498, -6.2603)),
    Country.AT: ("Europe/Vienna", "de-AT", GeoCoordinate(48.2082, 16.3738)),
    Country.BE: ("Europe/Brussels", "fr-BE", GeoCoordinate(50.8503, 4.3517)),
    # Asia/Oceanía
    Country.JP: ("Asia/Tokyo", "ja-JP", GeoCoordinate(35.6762, 139.6503)),
    Country.AU: ("Australia/Sydney", "en-AU", GeoCoordinate(-33.8688, 151.2093)),
    Country.NZ: ("Pacific/Auckland", "en-NZ", GeoCoordinate(-36.8485, 174.7633)),
    # Otros
    Country.CA: ("America/Toronto", "en-CA", GeoCoordinate(43.6532, -79.3832)),
    Country.TH: ("Asia/Bangkok", "th-TH", GeoCoordinate(13.7563, 100.5018)),
}

# Viewports "mobile-like" plausibles (Chrome mobile / iOS Safari mobile).
_MOBILE_VIEWPORTS: Final[tuple[tuple[int, int], ...]] = (
    (375, 667),  # iPhone SE / 6/7/8
    (390, 844),  # iPhone 12/13/14
    (412, 915),  # Pixel 6/7
    (360, 800),  # Galaxy S20
)

# Viewports desktop habituales.
_DESKTOP_VIEWPORTS: Final[tuple[tuple[int, int], ...]] = (
    (1366, 768),
    (1440, 900),
    (1536, 864),
    (1600, 900),
    (1920, 1080),
)


def _jitter_geo(coord: GeoCoordinate, *, radius_km: float = 5.0) -> GeoCoordinate:
    """Añade ruido ~radius_km a una coordenada (anti-fingerprint trivial)."""
    delta_lat = (secrets.randbelow(2000) - 1000) / 1000 * (radius_km / 111.0)
    delta_lon = (secrets.randbelow(2000) - 1000) / 1000 * (radius_km / 111.0)
    return GeoCoordinate(
        latitude=max(-90.0, min(90.0, coord.latitude + delta_lat)),
        longitude=max(-180.0, min(180.0, coord.longitude + delta_lon)),
    )


class BrowserforgeFingerprintGenerator(IFingerprintGenerator):
    """Implementación de IFingerprintGenerator usando Browserforge para el UA.

    El generador subyacente devuelve fingerprints distintos en cada llamada
    (desktop por defecto), garantizando que dos cuentas en el mismo país
    tengan UAs/screens distintos pero locale y timezone coherentes.
    """

    def __init__(
        self,
        *,
        viewport_width: int = 1366,
        viewport_height: int = 768,
        mobile_probability: float = 0.20,
        rng: Random | None = None,
    ) -> None:
        if not 0.0 <= mobile_probability <= 1.0:
            raise ValueError("mobile_probability debe estar en [0,1]")
        self._default_viewport = (viewport_width, viewport_height)
        self._mobile_probability = mobile_probability
        self._rng = rng if rng is not None else Random()  # noqa: S311
        self._desktop_generator = _BFGenerator(device="desktop")
        self._mobile_generator = _BFGenerator(device="mobile")

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

        is_mobile = self._rng.random() < self._mobile_probability
        generator = self._mobile_generator if is_mobile else self._desktop_generator
        bf_fingerprint = generator.generate(locale=locale)

        # El viewport real (Playwright) lo elegimos coherente con desktop/mobile.
        # Usamos la pool predefinida (no el screen.width de browserforge, que
        # representa el SCREEN, no la ventana del browser).
        if is_mobile:
            viewport = self._rng.choice(_MOBILE_VIEWPORTS)
        else:
            viewport = self._rng.choice((self._default_viewport, *_DESKTOP_VIEWPORTS))

        return Fingerprint(
            user_agent=str(bf_fingerprint.navigator.userAgent),
            locale=locale,
            timezone_id=timezone_id,
            geolocation=_jitter_geo(capital),
            country=country,
            viewport_width=viewport[0],
            viewport_height=viewport[1],
        )
