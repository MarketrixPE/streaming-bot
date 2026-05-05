"""Generador v2: ExtendedFingerprint con UA-CH, JA4, H2, hardware y fonts.

Estrategia:
1. Reusa el generador v1 (`CoherentFingerprintGenerator`) para obtener la
   huella base coherente (UA + locale + TZ + geo + country).
2. Detecta engine + SO desde el UA elegido.
3. Compone los nuevos campos coherentemente:
     - Sec-CH-UA-* coherente con engine y SO.
     - JA4 hint coherente con engine.
     - H2 fingerprint coherente con engine.
     - Hardware profile estable por persona y coherente con SO.
     - Fonts pool coherente con SO.

NO se modifica nada del flow v1 ni del puerto IFingerprintGenerator: este
generador implementa el puerto (devolviendo `Fingerprint` base) y agrega
`coherent_for_extended` como API adicional.
"""

from __future__ import annotations

from streaming_bot.domain.ports.fingerprint import IFingerprintGenerator
from streaming_bot.domain.value_objects import Country, Fingerprint, ProxyEndpoint
from streaming_bot.domain.value_objects_v2 import ExtendedFingerprint
from streaming_bot.infrastructure.fingerprints.client_hints import (
    compute_client_hints,
    detect_engine,
    detect_os,
)
from streaming_bot.infrastructure.fingerprints.coherent_fingerprint import (
    CoherentFingerprintGenerator,
)
from streaming_bot.infrastructure.fingerprints.fonts_pool import fonts_for
from streaming_bot.infrastructure.fingerprints.h2_fingerprint import h2_for_engine
from streaming_bot.infrastructure.fingerprints.hardware_profile import hardware_for
from streaming_bot.infrastructure.fingerprints.ja4_hint import expected_ja4


class CoherentFingerprintGeneratorV2:
    """Implementa `IFingerprintGenerator` y agrega ExtendedFingerprint.

    Cumple estructuralmente el Protocol `IFingerprintGenerator` (Clean
    Architecture: el dominio NO importa de aqui), por lo que sigue siendo
    inyectable donde la capa de aplicacion espera el generador base.
    """

    def __init__(
        self,
        *,
        base_generator: IFingerprintGenerator | None = None,
        viewport_width: int = 1366,
        viewport_height: int = 768,
    ) -> None:
        # Composicion: si no se inyecta uno, instanciamos el v1 por defecto.
        # Esto facilita testing (se puede pasar un fake generator).
        self._base: IFingerprintGenerator = base_generator or CoherentFingerprintGenerator(
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )

    def coherent_for(
        self,
        proxy: ProxyEndpoint | None,
        *,
        fallback_country: Country = Country.US,
    ) -> Fingerprint:
        """Devuelve la huella base v1 (compatibilidad con consumidores actuales)."""
        return self._base.coherent_for(proxy, fallback_country=fallback_country)

    def coherent_for_extended(
        self,
        proxy: ProxyEndpoint | None,
        *,
        fallback_country: Country = Country.US,
        persona_id: str | None = None,
    ) -> ExtendedFingerprint:
        """Genera el ExtendedFingerprint con todos los campos v2.

        - `persona_id` (opcional pero RECOMENDADO en produccion): hace que la
          GPU/cores/memoria sean estables para la misma cuenta entre sesiones.
        """
        base = self._base.coherent_for(proxy, fallback_country=fallback_country)
        os_family = detect_os(base.user_agent)
        engine, major = detect_engine(base.user_agent)

        return ExtendedFingerprint(
            base=base,
            client_hints=compute_client_hints(base.user_agent),
            ja4=expected_ja4(engine, major),
            h2=h2_for_engine(engine),
            hardware=hardware_for(os_family, persona_id=persona_id),
            fonts=fonts_for(os_family),
            os_family=os_family,
            engine=engine,
        )
