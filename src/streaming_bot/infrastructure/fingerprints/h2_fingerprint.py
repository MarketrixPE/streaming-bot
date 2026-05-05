"""Pre-computa la Akamai HTTP/2 fingerprint string por engine.

Referencia: Akamai PoC "Passive Fingerprinting of HTTP/2 Clients" (2017,
vigente). Ver tambien las firmas H2 publicadas por Salesforce / FoxIO en
los datasets JA3+H2.

Formato:
    SETTINGS|WINDOW_UPDATE|PRIORITY|PSEUDO_HEADER_ORDER

- SETTINGS: pares ID:VALUE separados por ';' (Chrome / Safari) o ',' (Firefox).
- WINDOW_UPDATE: incremento WINDOW_UPDATE inicial.
- PRIORITY: priority frames pre-stream que envia Firefox; Chrome/Safari = '0'.
- PSEUDO_HEADER_ORDER: orden de pseudo-headers en HEADERS frame
  (m=:method, a=:authority, s=:scheme, p=:path).
"""

from __future__ import annotations

from streaming_bot.domain.value_objects_v2 import H2Fingerprint

# Fingerprints observados en capturas de browser real 2025-Q4. Refrescables.
_H2_BY_ENGINE: dict[str, H2Fingerprint] = {
    "chrome": H2Fingerprint(
        settings="1:65536;2:0;3:1000;4:6291456;6:262144",
        window_update="15663105",
        priority="0",
        pseudo_headers="m,a,s,p",
    ),
    # Edge comparte el stack BoringSSL/Chromium net -> mismo H2 fingerprint.
    "edge": H2Fingerprint(
        settings="1:65536;2:0;3:1000;4:6291456;6:262144",
        window_update="15663105",
        priority="0",
        pseudo_headers="m,a,s,p",
    ),
    "firefox": H2Fingerprint(
        settings="1:65536,4:131072,5:16384",
        window_update="12517377",
        # Firefox abre 6 priority streams iniciales (15.0+ con HTTP/2 dependency
        # tree). Cada entrada: stream:exclusive:dependency:weight.
        priority="3:0:0:201,5:0:0:101,7:0:0:1,9:0:7:1,11:0:3:1,13:0:0:241",
        pseudo_headers="m,p,a,s",
    ),
    "safari": H2Fingerprint(
        settings="2:0;3:100;4:2097152;8:1;9:1",
        window_update="10485760",
        priority="0",
        pseudo_headers="m,s,p,a",
    ),
}

# Default cuando engine == 'unknown': caemos en Chrome (engine dominante).
_DEFAULT_H2: H2Fingerprint = _H2_BY_ENGINE["chrome"]


def h2_for_engine(engine: str) -> H2Fingerprint:
    """Devuelve la H2 fingerprint canonica para el engine dado.

    Para engines no reconocidos retorna la huella de Chrome, que es la
    distribucion mayoritaria a nivel global (~75-80% market share).
    """
    return _H2_BY_ENGINE.get(engine, _DEFAULT_H2)
