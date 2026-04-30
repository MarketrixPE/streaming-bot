"""Puerto para generador de fingerprints coherentes."""

from __future__ import annotations

from typing import Protocol

from streaming_bot.domain.value_objects import Country, Fingerprint, ProxyEndpoint


class IFingerprintGenerator(Protocol):
    """Genera fingerprints donde país↔TZ↔geo↔locale↔UA son consistentes."""

    def coherent_for(
        self,
        proxy: ProxyEndpoint | None,
        *,
        fallback_country: Country = Country.US,
    ) -> Fingerprint:
        """Construye una huella coherente con el país del proxy.

        Si `proxy` es None, usa `fallback_country`.
        """
        ...
