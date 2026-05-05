"""Pre-computa el JA4/JA4_R fingerprint esperado por (engine, version).

Referencia: John Althouse, "JA4+ Network Fingerprinting" (FoxIO, 2023).
https://github.com/FoxIO-LLC/ja4

El browser driver (Patchright / Camoufox) consume este hint para validar
que la sesion TLS observada en la pasarela coincide con la huella declarada;
una divergencia indica fuga de stack (p.ej. el binario de Chromium se
actualizo y trae cipher suites distintos al esperado).

Formato JA4 (canonico):
    ja4_a = prot(t/q) + tls(13|12) + sni(d|i) + ciphers_NN + ext_NN + alpn_2
    ja4_b = sha256(sorted_ciphers)[:12]
    ja4_c = sha256(sorted_ext)[:12]
    ja4   = "{ja4_a}_{ja4_b}_{ja4_c}"
"""

from __future__ import annotations

import hashlib

from streaming_bot.domain.value_objects_v2 import JA4Hint

# Cipher suites IANA (hex sin prefijo 0x) tipicamente ofrecidas por cada engine
# en TLS 1.3 ClientHello. Lista aproximada extraida de capturas de browser real
# 2025-Q4 (refrescable trimestralmente igual que el pool de UAs).
_CHROME_CIPHERS: tuple[str, ...] = (
    "1301",  # TLS_AES_128_GCM_SHA256
    "1302",  # TLS_AES_256_GCM_SHA384
    "1303",  # TLS_CHACHA20_POLY1305_SHA256
    "c02b",  # ECDHE-ECDSA-AES128-GCM
    "c02f",  # ECDHE-RSA-AES128-GCM
    "c02c",  # ECDHE-ECDSA-AES256-GCM
    "c030",  # ECDHE-RSA-AES256-GCM
    "cca9",  # ECDHE-ECDSA-CHACHA20-POLY1305
    "cca8",  # ECDHE-RSA-CHACHA20-POLY1305
    "c013",  # ECDHE-RSA-AES128-SHA
    "c014",  # ECDHE-RSA-AES256-SHA
    "009c",  # AES128-GCM-SHA256
    "009d",  # AES256-GCM-SHA384
    "002f",  # AES128-SHA
    "0035",  # AES256-SHA
)

_CHROME_EXTENSIONS: tuple[str, ...] = (
    "0000",  # server_name
    "0017",  # extended_master_secret
    "ff01",  # renegotiation_info
    "000a",  # supported_groups
    "000b",  # ec_point_formats
    "0023",  # session_ticket
    "0010",  # ALPN
    "0005",  # status_request
    "000d",  # signature_algorithms
    "0012",  # signed_certificate_timestamp
    "0033",  # key_share
    "002d",  # psk_key_exchange_modes
    "002b",  # supported_versions
    "001b",  # compress_certificate
    "001c",  # record_size_limit
    "0029",  # pre_shared_key
)

_FIREFOX_CIPHERS: tuple[str, ...] = (
    "1301",
    "1303",
    "1302",
    "c02b",
    "c02f",
    "cca9",
    "cca8",
    "c02c",
    "c030",
    "c013",
    "c014",
    "0033",
    "0039",
    "009c",
    "009d",
    "002f",
    "0035",
)

_FIREFOX_EXTENSIONS: tuple[str, ...] = (
    "0000",
    "0017",
    "ff01",
    "000a",
    "000b",
    "0023",
    "0010",
    "0005",
    "0022",
    "000d",
    "0028",
    "002b",
    "002d",
    "0033",
    "001c",
)

_SAFARI_CIPHERS: tuple[str, ...] = (
    "1301",
    "1302",
    "1303",
    "c02c",
    "c02b",
    "cca9",
    "c030",
    "c02f",
    "cca8",
    "c024",
    "c023",
    "c00a",
    "c009",
    "c014",
    "c013",
    "009d",
    "009c",
    "0035",
    "002f",
)

_SAFARI_EXTENSIONS: tuple[str, ...] = (
    "0000",
    "0017",
    "ff01",
    "000a",
    "000b",
    "000d",
    "0010",
    "0005",
    "0012",
    "0033",
    "002b",
    "002d",
    "001b",
    "001c",
)

# Truncamiento canonico que define el spec JA4 para los hashes b y c.
_JA4_HASH_TRUNCATE = 12


def _hash_list(items: tuple[str, ...]) -> str:
    """SHA-256 de la lista ordenada y truncado a 12 hex chars (spec JA4)."""
    payload = ",".join(sorted(items)).encode("ascii")
    # nosec B324: SHA-256 NO se usa aqui como password digest sino como
    # truncado canonico definido en la spec JA4 (publica, no es secreto).
    return hashlib.sha256(payload).hexdigest()[:_JA4_HASH_TRUNCATE]


def _ciphers_extensions_for(engine: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Devuelve (ciphers, extensions) por engine; default Chrome para 'unknown'."""
    if engine in {"chrome", "edge"}:
        return _CHROME_CIPHERS, _CHROME_EXTENSIONS
    if engine == "firefox":
        return _FIREFOX_CIPHERS, _FIREFOX_EXTENSIONS
    if engine == "safari":
        return _SAFARI_CIPHERS, _SAFARI_EXTENSIONS
    return _CHROME_CIPHERS, _CHROME_EXTENSIONS


def expected_ja4(engine: str, major_version: int) -> JA4Hint:
    """Devuelve el JA4Hint plausible y deterministico para el engine dado.

    El hint se usa como ORACULO: la red real debe coincidir con este string,
    si no el caller debe asumir que el browser fue actualizado y refrescar
    el pool. NO se usa para generar el handshake (eso lo hace el binario de
    Chromium/Patchright internamente).
    """
    ciphers, exts = _ciphers_extensions_for(engine)

    cnt_ciphers = f"{len(ciphers):02d}"
    cnt_exts = f"{len(exts):02d}"
    # t = TCP, 13 = TLS 1.3, d = SNI por dominio, h2 = ALPN HTTP/2.
    ja4_a = f"t13d{cnt_ciphers}{cnt_exts}h2"
    ja4_b = _hash_list(ciphers)
    ja4_c = _hash_list(exts)
    ja4_full = f"{ja4_a}_{ja4_b}_{ja4_c}"

    raw_ciphers = ",".join(ciphers)
    raw_exts = ",".join(exts)
    ja4_r = f"{ja4_a}_{raw_ciphers}_{raw_exts}"

    return JA4Hint(
        ja4=ja4_full,
        ja4_r=ja4_r,
        engine=engine,
        engine_major_version=major_version,
    )
