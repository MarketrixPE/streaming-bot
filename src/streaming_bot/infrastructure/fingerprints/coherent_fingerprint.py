"""Generador de fingerprints coherentes IP - TZ - Geo - Locale - UA - OS.

A diferencia del bot original que asignaba random.choice() a cada campo
INDEPENDIENTEMENTE (un proxy en EE.UU. con timezone Antarctica/Vostok y
locale ja-JP es una bandera roja inmediata), este generador correlaciona
todas las dimensiones a partir del pais.

Mejoras Sprint Mes-1:
- Tabla _COUNTRY_PROFILES cubre TODOS los paises del enum Country (no solo
  10 cae-en-US como antes).
- User-Agent NO se elige por secrets.choice global: ahora se selecciona
  segun una distribucion realista de SO por pais (Stats 2025-2026 de
  StatCounter para Spotify Web user base) y se garantiza coherencia con
  el campo "platform" del Client Hints (a futuro v2 sumara JA4 y CH).
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

# ── Pool de UAs por sistema operativo (Chrome 130, Firefox 130, Safari 18) ──
# Refrescar trimestralmente. Mantener Chrome dominante (75-80%) por share real.
_UA_BY_OS: dict[str, tuple[str, ...]] = {
    "Windows": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    ),
    "macOS": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.0 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.1 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:130.0) Gecko/20100101 Firefox/130.0",
    ),
    "Linux": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ),
}

# Distribucion observada de SO por geo. Suma = 100. Fuente: StatCounter
# Desktop OS market share Q1-Q3 2025 (aproximada por region).
_OS_DISTRIBUTION_BY_COUNTRY: dict[Country, tuple[tuple[str, int], ...]] = {
    # LATAM: Windows muy dominante, mac bajo, linux residual.
    Country.PE: (("Windows", 88), ("macOS", 9), ("Linux", 3)),
    Country.MX: (("Windows", 86), ("macOS", 11), ("Linux", 3)),
    Country.US: (("Windows", 64), ("macOS", 30), ("Linux", 6)),
    Country.CL: (("Windows", 85), ("macOS", 12), ("Linux", 3)),
    Country.AR: (("Windows", 87), ("macOS", 10), ("Linux", 3)),
    Country.CO: (("Windows", 87), ("macOS", 10), ("Linux", 3)),
    Country.EC: (("Windows", 89), ("macOS", 8), ("Linux", 3)),
    Country.BO: (("Windows", 90), ("macOS", 7), ("Linux", 3)),
    Country.DO: (("Windows", 86), ("macOS", 11), ("Linux", 3)),
    Country.PR: (("Windows", 70), ("macOS", 26), ("Linux", 4)),
    Country.VE: (("Windows", 89), ("macOS", 8), ("Linux", 3)),
    Country.UY: (("Windows", 84), ("macOS", 13), ("Linux", 3)),
    Country.PY: (("Windows", 89), ("macOS", 8), ("Linux", 3)),
    Country.PA: (("Windows", 84), ("macOS", 13), ("Linux", 3)),
    Country.GT: (("Windows", 88), ("macOS", 9), ("Linux", 3)),
    Country.HN: (("Windows", 89), ("macOS", 8), ("Linux", 3)),
    Country.SV: (("Windows", 88), ("macOS", 9), ("Linux", 3)),
    Country.NI: (("Windows", 90), ("macOS", 7), ("Linux", 3)),
    Country.CR: (("Windows", 82), ("macOS", 15), ("Linux", 3)),
    Country.BR: (("Windows", 84), ("macOS", 13), ("Linux", 3)),
    # Europa: mix mas equilibrado.
    Country.ES: (("Windows", 76), ("macOS", 20), ("Linux", 4)),
    Country.GB: (("Windows", 65), ("macOS", 30), ("Linux", 5)),
    Country.CH: (("Windows", 68), ("macOS", 28), ("Linux", 4)),
    Country.DE: (("Windows", 73), ("macOS", 22), ("Linux", 5)),
    Country.FR: (("Windows", 72), ("macOS", 24), ("Linux", 4)),
    Country.IT: (("Windows", 78), ("macOS", 19), ("Linux", 3)),
    Country.PT: (("Windows", 79), ("macOS", 18), ("Linux", 3)),
    Country.NL: (("Windows", 70), ("macOS", 26), ("Linux", 4)),
    Country.SE: (("Windows", 70), ("macOS", 26), ("Linux", 4)),
    Country.NO: (("Windows", 70), ("macOS", 26), ("Linux", 4)),
    Country.DK: (("Windows", 70), ("macOS", 26), ("Linux", 4)),
    Country.FI: (("Windows", 70), ("macOS", 26), ("Linux", 4)),
    Country.IE: (("Windows", 67), ("macOS", 29), ("Linux", 4)),
    Country.AT: (("Windows", 75), ("macOS", 21), ("Linux", 4)),
    Country.BE: (("Windows", 73), ("macOS", 23), ("Linux", 4)),
    # Asia / Oceania.
    Country.JP: (("Windows", 76), ("macOS", 20), ("Linux", 4)),
    Country.AU: (("Windows", 65), ("macOS", 30), ("Linux", 5)),
    Country.NZ: (("Windows", 65), ("macOS", 30), ("Linux", 5)),
    # Asia: targets del router asiatico (JioSaavn IN, KKBox TW/HK/KR, NetEase CN).
    # India y China son fuertemente Windows-dominantes (parque con muchos OEM
    # entry-level + cibers). Korea/Taiwan tienen mas Mac y mas Linux que el
    # resto de Asia por hub tecnologico y cultura developer.
    Country.IN: (("Windows", 90), ("macOS", 6), ("Linux", 4)),
    Country.TW: (("Windows", 72), ("macOS", 22), ("Linux", 6)),
    Country.HK: (("Windows", 70), ("macOS", 26), ("Linux", 4)),
    Country.CN: (("Windows", 88), ("macOS", 8), ("Linux", 4)),
    Country.KR: (("Windows", 70), ("macOS", 24), ("Linux", 6)),
    # Otros.
    Country.CA: (("Windows", 64), ("macOS", 31), ("Linux", 5)),
    Country.TH: (("Windows", 84), ("macOS", 13), ("Linux", 3)),
}


# ── Tabla de coherencia: pais -> (timezone canonica, locale principal, capital) ──
# Cobertura COMPLETA del enum Country (auditoria Mes-1: ya no cae en US).
_COUNTRY_PROFILES: dict[Country, tuple[str, str, GeoCoordinate]] = {
    # Latinoamerica
    Country.PE: ("America/Lima", "es-PE", GeoCoordinate(-12.0464, -77.0428)),
    Country.MX: ("America/Mexico_City", "es-MX", GeoCoordinate(19.4326, -99.1332)),
    Country.US: ("America/New_York", "en-US", GeoCoordinate(40.7128, -74.0060)),
    Country.CL: ("America/Santiago", "es-CL", GeoCoordinate(-33.4489, -70.6693)),
    Country.AR: ("America/Argentina/Buenos_Aires", "es-AR", GeoCoordinate(-34.6037, -58.3816)),
    Country.CO: ("America/Bogota", "es-CO", GeoCoordinate(4.7110, -74.0721)),
    Country.EC: ("America/Guayaquil", "es-EC", GeoCoordinate(-0.1807, -78.4678)),
    Country.BO: ("America/La_Paz", "es-BO", GeoCoordinate(-16.4897, -68.1193)),
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
    # Asia / Oceania
    Country.JP: ("Asia/Tokyo", "ja-JP", GeoCoordinate(35.6762, 139.6503)),
    Country.AU: ("Australia/Sydney", "en-AU", GeoCoordinate(-33.8688, 151.2093)),
    Country.NZ: ("Pacific/Auckland", "en-NZ", GeoCoordinate(-36.8485, 174.7633)),
    # Asia continental: capitales/hubs de cada DSP del router asiatico.
    Country.IN: ("Asia/Kolkata", "hi-IN", GeoCoordinate(28.6139, 77.2090)),  # New Delhi
    Country.TW: ("Asia/Taipei", "zh-TW", GeoCoordinate(25.0330, 121.5654)),  # Taipei
    Country.HK: ("Asia/Hong_Kong", "zh-HK", GeoCoordinate(22.3193, 114.1694)),
    Country.CN: ("Asia/Shanghai", "zh-CN", GeoCoordinate(31.2304, 121.4737)),  # Shanghai
    Country.KR: ("Asia/Seoul", "ko-KR", GeoCoordinate(37.5665, 126.9780)),
    # Otros
    Country.CA: ("America/Toronto", "en-CA", GeoCoordinate(43.6532, -79.3832)),
    Country.TH: ("Asia/Bangkok", "th-TH", GeoCoordinate(13.7563, 100.5018)),
}


# Default profile cuando llega un Country no listado (no deberia ocurrir si
# los enums estan sincronizados; defensivo solo).
_DEFAULT_PROFILE: tuple[str, str, GeoCoordinate] = (
    "America/New_York",
    "en-US",
    GeoCoordinate(40.7128, -74.0060),
)
_DEFAULT_OS_DISTRIBUTION: tuple[tuple[str, int], ...] = (
    ("Windows", 70),
    ("macOS", 25),
    ("Linux", 5),
)


def _jitter(coord: GeoCoordinate, *, radius_km: float = 5.0) -> GeoCoordinate:
    """Anade ruido de aprox. 5km a una coordenada para que dos cuentas no
    coincidan exactamente.

    1 grado latitud = 111 km, 1 grado longitud = 111 * cos(lat) km. Aproximacion
    suficiente para nuestro proposito (no es navegacion aerea).
    """
    delta_lat = (secrets.randbelow(2000) - 1000) / 1000 * (radius_km / 111.0)
    delta_lon = (secrets.randbelow(2000) - 1000) / 1000 * (radius_km / 111.0)
    return GeoCoordinate(
        latitude=max(-90.0, min(90.0, coord.latitude + delta_lat)),
        longitude=max(-180.0, min(180.0, coord.longitude + delta_lon)),
    )


def _weighted_choice(buckets: tuple[tuple[str, int], ...]) -> str:
    """Elige una clave segun pesos enteros usando randbelow CSPRNG."""
    total = sum(weight for _, weight in buckets)
    if total <= 0:
        return buckets[0][0]
    pick = secrets.randbelow(total)
    cumulative = 0
    for key, weight in buckets:
        cumulative += weight
        if pick < cumulative:
            return key
    return buckets[-1][0]


def _select_user_agent(country: Country) -> str:
    """Selecciona un UA coherente con la distribucion de SO del pais.

    Garantiza:
    - SO elegido segun StatCounter market share aproximado para la geo.
    - UA dentro del pool de ese SO (Chrome dominante, Firefox/Safari residual).
    """
    distribution = _OS_DISTRIBUTION_BY_COUNTRY.get(country, _DEFAULT_OS_DISTRIBUTION)
    chosen_os = _weighted_choice(distribution)
    pool = _UA_BY_OS.get(chosen_os, _UA_BY_OS["Windows"])
    return secrets.choice(pool)


class CoherentFingerprintGenerator(IFingerprintGenerator):
    """Implementacion por defecto: tabla estatica + jitter geografico + UA por OS."""

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
        timezone_id, locale, capital = _COUNTRY_PROFILES.get(country, _DEFAULT_PROFILE)
        return Fingerprint(
            user_agent=_select_user_agent(country),
            locale=locale,
            timezone_id=timezone_id,
            geolocation=_jitter(capital),
            country=country,
            viewport_width=self._viewport_width,
            viewport_height=self._viewport_height,
        )
