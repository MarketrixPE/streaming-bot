"""Value objects v2 del fingerprint extendido.

Reglas:
- Inmutables (frozen=True, slots=True), igual que el VO base.
- Sin I/O ni dependencias externas (solo stdlib + el VO base de v1).
- ExtendedFingerprint compone (no hereda) Fingerprint para evitar conflictos
  de slots/orden de campos por defecto entre dataclasses anidados.

Cobertura de superficie de huella v2:
- Client Hints (UA-CH) coherentes con el UA y el SO.
- JA4 / JA4_R hint pre-computado por (engine, version) -- John Althouse 2023.
- Akamai HTTP/2 fingerprint string por engine.
- Hardware profile estable: GPU (vendor + renderer), cores, memoria.
- Pool de fuentes realista por SO.
"""

from __future__ import annotations

from dataclasses import dataclass

from streaming_bot.domain.value_objects import Country, Fingerprint, GeoCoordinate

# Familias de SO soportadas por el resto del stack v2.
_VALID_OS_FAMILIES: frozenset[str] = frozenset({"Windows", "macOS", "Linux"})

# Engines de browser cubiertos por las tablas de JA4/H2/UA-CH.
_VALID_ENGINES: frozenset[str] = frozenset({"chrome", "edge", "firefox", "safari", "unknown"})


@dataclass(frozen=True, slots=True)
class ClientHints:
    """Cabeceras Sec-CH-UA-* que el browser presenta junto con el UA.

    Para engines no-Chromium (Firefox / Safari) los campos `sec_ch_ua` y
    `sec_ch_ua_full_version_list` quedan en None: el navegador real no emite
    esas cabeceras y enviarlas seria una bandera roja inmediata para
    fingerprinters server-side.
    """

    sec_ch_ua: str | None
    sec_ch_ua_platform: str  # Comilla doble incluida: '"Windows"', '"macOS"', '"Linux"'
    sec_ch_ua_mobile: str  # "?0" desktop, "?1" mobile
    sec_ch_ua_platform_version: str  # '"15.0.0"' (Win 11), '"14.6.0"' (macOS 14.6)
    sec_ch_ua_arch: str  # '"x86"', '"arm"'
    sec_ch_ua_bitness: str  # '"64"' o '"32"'
    sec_ch_ua_full_version_list: str | None

    def as_headers(self) -> dict[str, str]:
        """Devuelve solo las cabeceras que el browser envia realmente."""
        headers: dict[str, str] = {
            "Sec-CH-UA-Platform": self.sec_ch_ua_platform,
            "Sec-CH-UA-Mobile": self.sec_ch_ua_mobile,
            "Sec-CH-UA-Platform-Version": self.sec_ch_ua_platform_version,
            "Sec-CH-UA-Arch": self.sec_ch_ua_arch,
            "Sec-CH-UA-Bitness": self.sec_ch_ua_bitness,
        }
        if self.sec_ch_ua is not None:
            headers["Sec-CH-UA"] = self.sec_ch_ua
        if self.sec_ch_ua_full_version_list is not None:
            headers["Sec-CH-UA-Full-Version-List"] = self.sec_ch_ua_full_version_list
        return headers


@dataclass(frozen=True, slots=True)
class JA4Hint:
    """JA4 / JA4_R fingerprint pre-computado para validacion de la sesion TLS.

    Formato JA4 canonico (Althouse 2023, "JA4+ Network Fingerprinting"):
        ja4_a = prot(t/q) + tls(13|12) + sni(d|i) + ciphers(NN) + ext(NN) + alpn(2)
        ja4_b = sha256(sorted_ciphers)[:12]
        ja4_c = sha256(sorted_extensions)[:12]
        ja4   = "{ja4_a}_{ja4_b}_{ja4_c}"

    `ja4_r` es la "raw" form (ciphers y extensiones sin hashear) util para
    diagnostico y para que el browser driver (Patchright / Camoufox) compare
    su handshake real contra el esperado.
    """

    ja4: str
    ja4_r: str
    engine: str
    engine_major_version: int


@dataclass(frozen=True, slots=True)
class H2Fingerprint:
    """Akamai HTTP/2 fingerprint string por engine de browser.

    Formato Akamai (PoC 2017, vigente):
        SETTINGS|WINDOW_UPDATE|PRIORITY|PSEUDO_HEADER_ORDER

    Donde:
      - SETTINGS:  ID:VALUE pares separados por ';' (Chrome) o ',' (Firefox).
      - WINDOW_UPDATE: incremento WINDOW_UPDATE inicial.
      - PRIORITY: priority frames pre-stream que envia el browser (Firefox los
        envia, Chrome/Safari no -> "0").
      - PSEUDO_HEADER_ORDER: orden de pseudo-headers en HEADERS frame
        (m=:method, a=:authority, s=:scheme, p=:path).
    """

    settings: str
    window_update: str
    priority: str
    pseudo_headers: str

    def as_akamai_string(self) -> str:
        """Devuelve el fingerprint Akamai en una sola string."""
        return f"{self.settings}|{self.window_update}|{self.priority}|{self.pseudo_headers}"


@dataclass(frozen=True, slots=True)
class GpuProfile:
    """Perfil estable WebGL / Canvas / AudioContext.

    Los `*_seed` son enteros que el browser driver inyecta como seeds
    deterministicas para las tecnicas de canvas / audio fingerprinting:
    el mismo persona => el mismo seed => el mismo hash de canvas y audio,
    de forma que la huella de WebGL/Canvas/AudioContext es ESTABLE entre
    sesiones de la misma cuenta (no se randomiza por sesion).
    """

    vendor: str  # WebGL UNMASKED_VENDOR_WEBGL
    renderer: str  # WebGL UNMASKED_RENDERER_WEBGL
    canvas_noise_seed: int
    audio_context_seed: int


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    """`navigator.hardwareConcurrency` + `navigator.deviceMemory` + GPU."""

    hardware_concurrency: int  # 4 | 8 | 12 | 16
    device_memory_gb: int  # 4 | 8 | 16
    gpu: GpuProfile


@dataclass(frozen=True, slots=True)
class ExtendedFingerprint:
    """Fingerprint v2: huella base + UA-CH + JA4 + H2 + hardware + fonts.

    Diseno por composicion (no por herencia) porque mezclar dataclasses
    `frozen + slots` con campos por defecto en una jerarquia es fragil; ademas
    asi se preserva el VO base sin tocar.
    """

    base: Fingerprint
    client_hints: ClientHints
    ja4: JA4Hint
    h2: H2Fingerprint
    hardware: HardwareProfile
    fonts: tuple[str, ...]
    os_family: str  # "Windows" | "macOS" | "Linux"
    engine: str  # "chrome" | "edge" | "firefox" | "safari" | "unknown"

    def __post_init__(self) -> None:
        if self.os_family not in _VALID_OS_FAMILIES:
            raise ValueError(f"os_family invalido: {self.os_family}")
        if self.engine not in _VALID_ENGINES:
            raise ValueError(f"engine invalido: {self.engine}")
        if not self.fonts:
            raise ValueError("fonts pool no puede estar vacio")

    # Accesores de delegacion comodos para no tener que escribir fp.base.* siempre.
    @property
    def user_agent(self) -> str:
        return self.base.user_agent

    @property
    def country(self) -> Country:
        return self.base.country

    @property
    def locale(self) -> str:
        return self.base.locale

    @property
    def timezone_id(self) -> str:
        return self.base.timezone_id

    @property
    def geolocation(self) -> GeoCoordinate:
        return self.base.geolocation
