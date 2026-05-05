"""Tests del Coherent Fingerprint Engine v2.

Cobertura:
- ExtendedFingerprint VO: invariantes y delegacion al VO base.
- ClientHints: derivacion coherente desde UA + SO.
- JA4 hint: formato canonico, deterministico por engine.
- H2 fingerprint: por engine, formato Akamai.
- HardwareProfile: estable por persona_id, valida pools.
- FontsPool: existencia de fuentes signature por SO.
- CoherentFingerprintGeneratorV2: coherencia transversal pais -> UA -> CH ->
  JA4 -> H2 -> hardware -> fonts.
"""

from __future__ import annotations

import re

import pytest

from streaming_bot.domain.value_objects import Country, ProxyEndpoint
from streaming_bot.domain.value_objects_v2 import (
    ClientHints,
    ExtendedFingerprint,
    GpuProfile,
    H2Fingerprint,
    HardwareProfile,
    JA4Hint,
)
from streaming_bot.infrastructure.fingerprints.client_hints import (
    compute_client_hints,
    detect_engine,
    detect_os,
)
from streaming_bot.infrastructure.fingerprints.coherent_fingerprint import (
    CoherentFingerprintGenerator,
)
from streaming_bot.infrastructure.fingerprints.coherent_fingerprint_v2 import (
    CoherentFingerprintGeneratorV2,
)
from streaming_bot.infrastructure.fingerprints.fonts_pool import fonts_for
from streaming_bot.infrastructure.fingerprints.h2_fingerprint import h2_for_engine
from streaming_bot.infrastructure.fingerprints.hardware_profile import hardware_for
from streaming_bot.infrastructure.fingerprints.ja4_hint import expected_ja4

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def gen_v2() -> CoherentFingerprintGeneratorV2:
    return CoherentFingerprintGeneratorV2()


CHROME_WIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
CHROME_MAC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
FIREFOX_WIN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0"
SAFARI_MAC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15"
)
EDGE_WIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
)
LINUX_CHROME_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# detect_engine / detect_os
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ua", "expected_engine", "expected_major"),
    [
        (CHROME_WIN_UA, "chrome", 130),
        (CHROME_MAC_UA, "chrome", 130),
        (FIREFOX_WIN_UA, "firefox", 130),
        (SAFARI_MAC_UA, "safari", 18),
        (EDGE_WIN_UA, "edge", 130),
        (LINUX_CHROME_UA, "chrome", 131),
        ("Mozilla/5.0 sin tokens conocidos", "unknown", 0),
    ],
)
def test_detect_engine(ua: str, expected_engine: str, expected_major: int) -> None:
    engine, major = detect_engine(ua)
    assert engine == expected_engine
    assert major == expected_major


@pytest.mark.parametrize(
    ("ua", "expected_os"),
    [
        (CHROME_WIN_UA, "Windows"),
        (FIREFOX_WIN_UA, "Windows"),
        (CHROME_MAC_UA, "macOS"),
        (SAFARI_MAC_UA, "macOS"),
        (LINUX_CHROME_UA, "Linux"),
        ("Mozilla/5.0 (Unknown)", "Linux"),  # default conservador
    ],
)
def test_detect_os(ua: str, expected_os: str) -> None:
    assert detect_os(ua) == expected_os


# ---------------------------------------------------------------------------
# compute_client_hints
# ---------------------------------------------------------------------------


def test_chrome_emits_sec_ch_ua() -> None:
    ch = compute_client_hints(CHROME_WIN_UA)
    assert ch.sec_ch_ua is not None
    assert "Chromium" in ch.sec_ch_ua
    assert "Google Chrome" in ch.sec_ch_ua
    assert 'v="130"' in ch.sec_ch_ua
    assert ch.sec_ch_ua_full_version_list is not None
    assert "130.0." in ch.sec_ch_ua_full_version_list
    assert ch.sec_ch_ua_platform == '"Windows"'
    assert ch.sec_ch_ua_mobile == "?0"
    assert ch.sec_ch_ua_arch == '"x86"'
    assert ch.sec_ch_ua_bitness == '"64"'


def test_edge_emits_microsoft_edge_brand() -> None:
    ch = compute_client_hints(EDGE_WIN_UA)
    assert ch.sec_ch_ua is not None
    assert "Microsoft Edge" in ch.sec_ch_ua
    assert "Google Chrome" not in ch.sec_ch_ua


def test_firefox_does_not_emit_sec_ch_ua() -> None:
    """Firefox NO envia Sec-CH-UA por spec; emitirla es bandera roja."""
    ch = compute_client_hints(FIREFOX_WIN_UA)
    assert ch.sec_ch_ua is None
    assert ch.sec_ch_ua_full_version_list is None
    # Pero las cabeceras "neutras" SI las completamos
    assert ch.sec_ch_ua_platform == '"Windows"'


def test_safari_does_not_emit_sec_ch_ua() -> None:
    ch = compute_client_hints(SAFARI_MAC_UA)
    assert ch.sec_ch_ua is None
    assert ch.sec_ch_ua_full_version_list is None
    assert ch.sec_ch_ua_platform == '"macOS"'


def test_client_hints_platform_version_per_os() -> None:
    assert compute_client_hints(CHROME_WIN_UA).sec_ch_ua_platform_version == '"15.0.0"'
    assert compute_client_hints(CHROME_MAC_UA).sec_ch_ua_platform_version == '"14.6.0"'
    assert compute_client_hints(LINUX_CHROME_UA).sec_ch_ua_platform_version == '"6.5.0"'


def test_client_hints_as_headers_omits_none_for_firefox() -> None:
    ch = compute_client_hints(FIREFOX_WIN_UA)
    headers = ch.as_headers()
    assert "Sec-CH-UA" not in headers
    assert "Sec-CH-UA-Full-Version-List" not in headers
    assert headers["Sec-CH-UA-Platform"] == '"Windows"'
    assert headers["Sec-CH-UA-Mobile"] == "?0"


def test_client_hints_as_headers_includes_chrome_brand() -> None:
    headers = compute_client_hints(CHROME_WIN_UA).as_headers()
    assert "Sec-CH-UA" in headers
    assert "Sec-CH-UA-Full-Version-List" in headers


# ---------------------------------------------------------------------------
# JA4 hint
# ---------------------------------------------------------------------------


_JA4_RE = re.compile(r"^t13d\d{2}\d{2}h2_[0-9a-f]{12}_[0-9a-f]{12}$")


@pytest.mark.parametrize("engine", ["chrome", "edge", "firefox", "safari"])
def test_ja4_format(engine: str) -> None:
    hint = expected_ja4(engine, 130)
    assert _JA4_RE.match(hint.ja4) is not None, f"JA4 mal formado: {hint.ja4}"
    assert hint.engine == engine
    assert hint.engine_major_version == 130


def test_ja4_is_deterministic_per_engine() -> None:
    """Mismo engine -> mismo JA4 (b y c son hashes deterministicos)."""
    a = expected_ja4("chrome", 130)
    b = expected_ja4("chrome", 131)  # version distinta NO afecta a las listas
    assert a.ja4 == b.ja4


def test_ja4_chrome_vs_firefox_diferen() -> None:
    chrome = expected_ja4("chrome", 130)
    firefox = expected_ja4("firefox", 130)
    assert chrome.ja4 != firefox.ja4


def test_ja4_unknown_engine_falls_back_to_chrome() -> None:
    chrome = expected_ja4("chrome", 130)
    unknown = expected_ja4("unknown", 0)
    assert chrome.ja4 == unknown.ja4
    assert unknown.engine == "unknown"


def test_ja4_r_contains_raw_ciphers_and_extensions() -> None:
    hint = expected_ja4("chrome", 130)
    assert hint.ja4_r.startswith("t13d")
    # ja4_r incluye raw ciphers separados por coma; debe contener varios.
    assert hint.ja4_r.count(",") > 10


# ---------------------------------------------------------------------------
# H2 fingerprint
# ---------------------------------------------------------------------------


def test_h2_chrome_and_edge_son_iguales() -> None:
    """Edge usa el stack net de Chromium -> misma huella H2."""
    assert h2_for_engine("chrome") == h2_for_engine("edge")


def test_h2_firefox_difiere_de_chrome() -> None:
    chrome = h2_for_engine("chrome")
    firefox = h2_for_engine("firefox")
    assert chrome.settings != firefox.settings
    # Firefox es el unico que envia priority frames pre-stream.
    assert firefox.priority != "0"
    assert chrome.priority == "0"


def test_h2_safari_pseudo_headers_difieren() -> None:
    chrome = h2_for_engine("chrome")
    safari = h2_for_engine("safari")
    assert chrome.pseudo_headers != safari.pseudo_headers


def test_h2_unknown_falls_back_to_chrome() -> None:
    assert h2_for_engine("unknown") == h2_for_engine("chrome")


def test_h2_akamai_string_format() -> None:
    chrome = h2_for_engine("chrome")
    parts = chrome.as_akamai_string().split("|")
    # Debe haber exactamente 4 secciones: settings | window | priority | headers
    assert len(parts) == 4


# ---------------------------------------------------------------------------
# HardwareProfile
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("os_family", ["Windows", "macOS", "Linux"])
def test_hardware_concurrency_in_whitelist(os_family: str) -> None:
    for _ in range(20):
        hw = hardware_for(os_family)
        assert hw.hardware_concurrency in {4, 8, 12, 16}
        assert hw.device_memory_gb in {4, 8, 16}


def test_hardware_persona_is_deterministic() -> None:
    a = hardware_for("Windows", persona_id="cuenta-001")
    b = hardware_for("Windows", persona_id="cuenta-001")
    assert a == b


def test_hardware_different_personas_produce_different_or_equal_profiles() -> None:
    """Diferentes persona_ids producen indices independientes; al menos uno
    debe variar en una muestra moderada (cores o gpu).
    """
    profiles = {
        hardware_for("Windows", persona_id=f"persona-{i}") for i in range(50)
    }
    assert len(profiles) > 1, "todos los personas devolvieron el mismo profile"


def test_hardware_macos_has_apple_or_intel_gpu() -> None:
    for i in range(30):
        hw = hardware_for("macOS", persona_id=f"mac-{i}")
        assert hw.gpu.vendor in {"Apple Inc.", "Intel Inc."}


def test_hardware_windows_has_chromium_angle_renderer() -> None:
    for i in range(30):
        hw = hardware_for("Windows", persona_id=f"win-{i}")
        assert "ANGLE" in hw.gpu.renderer


def test_hardware_unknown_os_falls_back_to_windows() -> None:
    hw = hardware_for("BeOS", persona_id="x")
    assert "ANGLE" in hw.gpu.renderer  # Pool de Windows


# ---------------------------------------------------------------------------
# Fonts pool
# ---------------------------------------------------------------------------


def test_fonts_windows_includes_signature_fonts() -> None:
    fonts = fonts_for("Windows")
    assert "Segoe UI" in fonts
    assert "Calibri" in fonts
    assert "Times New Roman" in fonts


def test_fonts_macos_includes_signature_fonts() -> None:
    fonts = fonts_for("macOS")
    assert "Helvetica" in fonts
    assert "San Francisco" in fonts
    assert "Lucida Grande" in fonts


def test_fonts_linux_includes_signature_fonts() -> None:
    fonts = fonts_for("Linux")
    assert "DejaVu Sans" in fonts
    assert "Ubuntu" in fonts


def test_fonts_unknown_os_falls_back_to_linux() -> None:
    assert fonts_for("Plan9") == fonts_for("Linux")


# ---------------------------------------------------------------------------
# ExtendedFingerprint VO
# ---------------------------------------------------------------------------


def _sample_extended() -> ExtendedFingerprint:
    base = CoherentFingerprintGenerator().coherent_for(None, fallback_country=Country.US)
    return ExtendedFingerprint(
        base=base,
        client_hints=compute_client_hints(base.user_agent),
        ja4=expected_ja4(*detect_engine(base.user_agent)),
        h2=h2_for_engine(detect_engine(base.user_agent)[0]),
        hardware=hardware_for(detect_os(base.user_agent), persona_id="x"),
        fonts=fonts_for(detect_os(base.user_agent)),
        os_family=detect_os(base.user_agent),
        engine=detect_engine(base.user_agent)[0],
    )


def test_extended_is_frozen() -> None:
    fp = _sample_extended()
    with pytest.raises(AttributeError):
        fp.engine = "firefox"  # type: ignore[misc]


def test_extended_delegates_to_base() -> None:
    fp = _sample_extended()
    assert fp.user_agent == fp.base.user_agent
    assert fp.country == fp.base.country
    assert fp.locale == fp.base.locale
    assert fp.timezone_id == fp.base.timezone_id
    assert fp.geolocation == fp.base.geolocation


def test_extended_invalid_os_raises() -> None:
    fp = _sample_extended()
    with pytest.raises(ValueError, match="os_family"):
        ExtendedFingerprint(
            base=fp.base,
            client_hints=fp.client_hints,
            ja4=fp.ja4,
            h2=fp.h2,
            hardware=fp.hardware,
            fonts=fp.fonts,
            os_family="BeOS",
            engine=fp.engine,
        )


def test_extended_invalid_engine_raises() -> None:
    fp = _sample_extended()
    with pytest.raises(ValueError, match="engine"):
        ExtendedFingerprint(
            base=fp.base,
            client_hints=fp.client_hints,
            ja4=fp.ja4,
            h2=fp.h2,
            hardware=fp.hardware,
            fonts=fp.fonts,
            os_family=fp.os_family,
            engine="netscape",
        )


def test_extended_empty_fonts_raises() -> None:
    fp = _sample_extended()
    with pytest.raises(ValueError, match="fonts"):
        ExtendedFingerprint(
            base=fp.base,
            client_hints=fp.client_hints,
            ja4=fp.ja4,
            h2=fp.h2,
            hardware=fp.hardware,
            fonts=(),
            os_family=fp.os_family,
            engine=fp.engine,
        )


# ---------------------------------------------------------------------------
# CoherentFingerprintGeneratorV2: coherencia transversal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("country", "expected_locale", "expected_tz"),
    [
        (Country.PE, "es-PE", "America/Lima"),
        (Country.MX, "es-MX", "America/Mexico_City"),
        (Country.ES, "es-ES", "Europe/Madrid"),
        (Country.JP, "ja-JP", "Asia/Tokyo"),
    ],
)
def test_v2_keeps_v1_coherence(
    gen_v2: CoherentFingerprintGeneratorV2,
    country: Country,
    expected_locale: str,
    expected_tz: str,
) -> None:
    proxy = ProxyEndpoint(scheme="http", host="x", port=80, country=country)
    fp = gen_v2.coherent_for_extended(proxy)
    assert fp.country == country
    assert fp.locale == expected_locale
    assert fp.timezone_id == expected_tz


def test_v2_coherent_for_returns_base(gen_v2: CoherentFingerprintGeneratorV2) -> None:
    """`coherent_for` (puerto IFingerprintGenerator) sigue funcionando."""
    fp = gen_v2.coherent_for(None, fallback_country=Country.GB)
    assert fp.country == Country.GB
    assert fp.locale == "en-GB"


def test_v2_os_engine_match_user_agent(gen_v2: CoherentFingerprintGeneratorV2) -> None:
    """El os_family y engine reportados deben ser consistentes con el UA elegido."""
    for _ in range(30):
        fp = gen_v2.coherent_for_extended(None, fallback_country=Country.PE)
        assert fp.os_family in {"Windows", "macOS", "Linux"}
        assert fp.engine in {"chrome", "firefox", "safari"}
        # Coherencia: los tokens del UA deben respaldar la deteccion.
        if fp.os_family == "Windows":
            assert "Windows NT" in fp.user_agent
        elif fp.os_family == "macOS":
            assert "Mac OS X" in fp.user_agent or "Macintosh" in fp.user_agent
        else:
            assert "Linux" in fp.user_agent


def test_v2_client_hints_platform_matches_os(gen_v2: CoherentFingerprintGeneratorV2) -> None:
    for _ in range(30):
        fp = gen_v2.coherent_for_extended(None, fallback_country=Country.MX)
        assert fp.client_hints.sec_ch_ua_platform == f'"{fp.os_family}"'


def test_v2_ja4_engine_matches_detected_engine(
    gen_v2: CoherentFingerprintGeneratorV2,
) -> None:
    for _ in range(30):
        fp = gen_v2.coherent_for_extended(None, fallback_country=Country.US)
        assert fp.ja4.engine == fp.engine


def test_v2_h2_chrome_engine_matches_chrome_h2(
    gen_v2: CoherentFingerprintGeneratorV2,
) -> None:
    """Para muestras donde se haya elegido Chrome, la H2 string debe ser la de Chrome."""
    for _ in range(40):
        fp = gen_v2.coherent_for_extended(None, fallback_country=Country.US)
        if fp.engine == "chrome":
            assert fp.h2 == h2_for_engine("chrome")
            break
    else:  # pragma: no cover - extremadamente improbable con 40 muestras
        pytest.fail("nunca se eligio Chrome en 40 muestras")


def test_v2_fonts_pool_matches_os(gen_v2: CoherentFingerprintGeneratorV2) -> None:
    for _ in range(30):
        fp = gen_v2.coherent_for_extended(None, fallback_country=Country.AR)
        assert fp.fonts == fonts_for(fp.os_family)


def test_v2_hardware_stable_per_persona(gen_v2: CoherentFingerprintGeneratorV2) -> None:
    """Mismo persona_id + mismo OS_family debe dar mismo HardwareProfile.

    Como el SO depende del UA elegido (CSPRNG), filtramos por mismas muestras
    cuando el UA del segundo intento queda en otro SO.
    """
    fp1 = gen_v2.coherent_for_extended(None, fallback_country=Country.US, persona_id="acc-1")
    # Repetir varias veces; al menos en una el SO debe coincidir.
    for _ in range(40):
        fp2 = gen_v2.coherent_for_extended(None, fallback_country=Country.US, persona_id="acc-1")
        if fp2.os_family == fp1.os_family:
            assert fp2.hardware == fp1.hardware
            return
    pytest.fail("no se logro repetir SO en 40 intentos para validar estabilidad")


def test_v2_inyeccion_de_base_generator() -> None:
    """Debe permitir inyectar un generador base distinto (Clean Architecture)."""
    base = CoherentFingerprintGenerator(viewport_width=1920, viewport_height=1080)
    gen = CoherentFingerprintGeneratorV2(base_generator=base)
    fp = gen.coherent_for_extended(None, fallback_country=Country.PE)
    assert fp.base.viewport_width == 1920
    assert fp.base.viewport_height == 1080


# ---------------------------------------------------------------------------
# Sanity de los VOs internos
# ---------------------------------------------------------------------------


def test_value_objects_son_hashables() -> None:
    """frozen=True => hashables; util para deduplicacion en sets."""
    chs = {compute_client_hints(CHROME_WIN_UA), compute_client_hints(CHROME_WIN_UA)}
    assert len(chs) == 1
    ja4s = {expected_ja4("chrome", 130), expected_ja4("chrome", 130)}
    assert len(ja4s) == 1


def test_h2_fingerprint_dataclass_construible_directamente() -> None:
    h2 = H2Fingerprint(
        settings="1:65536", window_update="65536", priority="0", pseudo_headers="m,a,s,p"
    )
    assert h2.as_akamai_string() == "1:65536|65536|0|m,a,s,p"


def test_gpu_profile_construible_directamente() -> None:
    gpu = GpuProfile(
        vendor="X", renderer="Y", canvas_noise_seed=1, audio_context_seed=2
    )
    hw = HardwareProfile(hardware_concurrency=8, device_memory_gb=16, gpu=gpu)
    assert hw.gpu is gpu


def test_ja4_hint_construible_directamente() -> None:
    j = JA4Hint(ja4="t13d1516h2_a_b", ja4_r="raw", engine="chrome", engine_major_version=130)
    assert j.engine == "chrome"


def test_client_hints_construible_directamente() -> None:
    ch = ClientHints(
        sec_ch_ua=None,
        sec_ch_ua_platform='"Windows"',
        sec_ch_ua_mobile="?0",
        sec_ch_ua_platform_version='"15.0.0"',
        sec_ch_ua_arch='"x86"',
        sec_ch_ua_bitness='"64"',
        sec_ch_ua_full_version_list=None,
    )
    headers = ch.as_headers()
    assert "Sec-CH-UA" not in headers
    assert headers["Sec-CH-UA-Mobile"] == "?0"
