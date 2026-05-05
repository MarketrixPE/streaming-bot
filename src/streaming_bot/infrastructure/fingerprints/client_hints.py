"""Computa Sec-CH-UA-* coherente desde el User-Agent + SO.

Reglas de coherencia:
- Engine y version se derivan del UA (regex sobre tokens estables).
- Plataforma se deriva del UA (Windows / macOS / Linux).
- Sec-CH-UA y Sec-CH-UA-Full-Version-List SOLO existen en Chromium
  (Chrome, Edge). Firefox y Safari NO emiten esas cabeceras: enviarlas
  es una bandera de fingerprinter para Akamai/Cloudflare.
- Sec-CH-UA-Platform-Version usa la version "moderna" del SO
  declarado (Win 11 = "15.0.0", macOS 14.6 = "14.6.0", Linux kernel
  recientes = "6.5.0").
"""

from __future__ import annotations

import re

from streaming_bot.domain.value_objects_v2 import ClientHints

# Tokens regex compilados una sola vez a nivel de modulo.
_CHROME_RE = re.compile(r"Chrome/(\d+)")
_FIREFOX_RE = re.compile(r"Firefox/(\d+)")
_SAFARI_RE = re.compile(r"Version/(\d+)(?:\.\d+)?")
_EDGE_RE = re.compile(r"Edg/(\d+)")

# Versiones representativas de plataforma usadas por Chromium en UA-CH.
# Refrescables si el ecosistema avanza (Win 12, macOS 15, kernel 6.x+, etc).
_CHROMIUM_PLATFORM_VERSIONS: dict[str, str] = {
    "Windows": "15.0.0",  # Sentinel de Windows 11/Server 2022 que reporta UA-CH
    "macOS": "14.6.0",
    "Linux": "6.5.0",
}

# "Build" plausible para Sec-CH-UA-Full-Version-List. No es critico que sea
# el build exacto del Chrome real; basta con un patron creible.
_CHROMIUM_FULL_BUILD = "0.6723.116"

# Constante pequena para evitar magic-number warnings en getter de version.
_NO_VERSION = 0


def detect_engine(user_agent: str) -> tuple[str, int]:
    """Devuelve `(engine, major_version)` a partir del UA.

    Engines reconocidos: 'chrome', 'edge', 'firefox', 'safari'. Si no detecta
    ninguno, devuelve `('unknown', 0)` -- el resto del stack v2 cae en
    defaults seguros.
    """
    if "Edg/" in user_agent:
        match = _EDGE_RE.search(user_agent)
        return ("edge", int(match.group(1)) if match else _NO_VERSION)
    if "Chrome/" in user_agent:
        match = _CHROME_RE.search(user_agent)
        return ("chrome", int(match.group(1)) if match else _NO_VERSION)
    if "Firefox/" in user_agent:
        match = _FIREFOX_RE.search(user_agent)
        return ("firefox", int(match.group(1)) if match else _NO_VERSION)
    if "Safari/" in user_agent and "Version/" in user_agent:
        match = _SAFARI_RE.search(user_agent)
        return ("safari", int(match.group(1)) if match else _NO_VERSION)
    return ("unknown", _NO_VERSION)


def detect_os(user_agent: str) -> str:
    """Devuelve 'Windows' | 'macOS' | 'Linux' a partir del UA."""
    if "Windows" in user_agent:
        return "Windows"
    if "Macintosh" in user_agent or "Mac OS X" in user_agent:
        return "macOS"
    return "Linux"


def _build_brand_string(engine: str, major: int, *, with_full_build: bool) -> str:
    """Construye el string canonico Sec-CH-UA o Sec-CH-UA-Full-Version-List.

    Mantiene el orden 'Not?A_Brand' -> 'Chromium' -> brand vendor que Chrome
    130+ envia en LATAM/EU (verificado contra capturas reales 2025-Q4).
    """
    brand = "Microsoft Edge" if engine == "edge" else "Google Chrome"
    if with_full_build:
        not_brand_v = "99.0.0.0"
        chromium_v = f"{major}.{_CHROMIUM_FULL_BUILD}"
        brand_v = f"{major}.{_CHROMIUM_FULL_BUILD}"
    else:
        not_brand_v = "99"
        chromium_v = f"{major}"
        brand_v = f"{major}"
    return (
        f'"Not?A_Brand";v="{not_brand_v}", '
        f'"Chromium";v="{chromium_v}", '
        f'"{brand}";v="{brand_v}"'
    )


def compute_client_hints(user_agent: str) -> ClientHints:
    """Calcula el set completo de Sec-CH-UA-* coherente con el UA dado."""
    engine, major = detect_engine(user_agent)
    os_family = detect_os(user_agent)

    # Sec-CH-UA-Platform va envuelto en comillas dobles literales.
    platform_value = f'"{os_family}"'
    platform_version = f'"{_CHROMIUM_PLATFORM_VERSIONS.get(os_family, "0.0.0")}"'

    # Sec-CH-UA-Arch. Apple Silicon NO se distingue desde UA porque Safari y
    # Chrome reportan 'Intel Mac OS X' por compatibilidad; tratamos macOS como
    # x86 a nivel UA-CH (alineado con lo que envia Chrome real).
    arch = '"x86"'
    bitness = '"64"'

    if engine in {"chrome", "edge"}:
        sec_ch_ua: str | None = _build_brand_string(engine, major, with_full_build=False)
        sec_ch_ua_full: str | None = _build_brand_string(engine, major, with_full_build=True)
    else:
        # Firefox / Safari NO emiten Sec-CH-UA. Mantener None.
        sec_ch_ua = None
        sec_ch_ua_full = None

    return ClientHints(
        sec_ch_ua=sec_ch_ua,
        sec_ch_ua_platform=platform_value,
        sec_ch_ua_mobile="?0",
        sec_ch_ua_platform_version=platform_version,
        sec_ch_ua_arch=arch,
        sec_ch_ua_bitness=bitness,
        sec_ch_ua_full_version_list=sec_ch_ua_full,
    )
