"""Router de DSPs asiaticos: dado un Country, elige la strategy correcta.

Politica:
- IN -> JioSaavn (volumen industrial, payout bajisimo).
- TW / HK -> KKBox (regional fuerte, payout decente).
- KR -> KKBox (fallback aceptable hasta integrar Genie/Melon en Q3).
- CN -> NetEase (requiere proxy CN obligatorio + cuentas con SIM +86).
- Cualquier otro Country -> UnsupportedCountryError.

Diseno DIP-friendly:
- El router NO instancia strategies por su cuenta; las recibe inyectadas.
  Asi tests pueden pasar dobles, y el container DI puede componer todo
  el grafo en una sola pasada.
- El router devuelve `IRichSiteStrategy` (no la clase concreta) para que
  consumidores aguas arriba sigan dependiendo solo de la abstraccion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.value_objects import Country

if TYPE_CHECKING:
    from streaming_bot.application.ports.site_strategy import IRichSiteStrategy
    from streaming_bot.presentation.strategies.jiosaavn import JioSaavnStrategy
    from streaming_bot.presentation.strategies.kkbox import KKBoxStrategy
    from streaming_bot.presentation.strategies.netease import NetEaseStrategy


class UnsupportedCountryError(DomainError):
    """El Country recibido no pertenece al cluster asiatico soportado.

    Heredamos de DomainError (no de TransientError ni PermanentError)
    porque es un error de configuracion de mas arriba (el orquestador
    no deberia haber enrutado un job con este pais a este router); el
    retry no aplica.
    """


# Buckets de paises por DSP. Tabla externalizada para que tests y otros
# modulos puedan introspectarla sin entrar al match interno del router.
_JIOSAAVN_COUNTRIES: frozenset[Country] = frozenset({Country.IN})
_KKBOX_COUNTRIES: frozenset[Country] = frozenset({Country.TW, Country.HK, Country.KR})
_NETEASE_COUNTRIES: frozenset[Country] = frozenset({Country.CN})

SUPPORTED_COUNTRIES: frozenset[Country] = (
    _JIOSAAVN_COUNTRIES | _KKBOX_COUNTRIES | _NETEASE_COUNTRIES
)


class AsiaDspRouter:
    """Resuelve la strategy adecuada para un Country del cluster asiatico.

    Uso tipico:
        router = AsiaDspRouter(jiosaavn=..., kkbox=..., netease=...)
        strategy = router.for_country(account.country)
        # strategy implementa IRichSiteStrategy: pasarlo al use case.

    Si el caller no sabe a priori si el pais es asiatico, puede consultar
    `is_supported(country)` antes de llamar a `for_country`.
    """

    def __init__(
        self,
        *,
        jiosaavn: JioSaavnStrategy,
        kkbox: KKBoxStrategy,
        netease: NetEaseStrategy,
    ) -> None:
        self._jiosaavn = jiosaavn
        self._kkbox = kkbox
        self._netease = netease

    @staticmethod
    def is_supported(country: Country) -> bool:
        """True si el Country pertenece al cluster asiatico soportado."""
        return country in SUPPORTED_COUNTRIES

    def for_country(self, country: Country) -> IRichSiteStrategy:
        """Devuelve la strategy correcta para el Country.

        Lanza `UnsupportedCountryError` si el pais no esta en
        `SUPPORTED_COUNTRIES`. La excepcion es deliberadamente expresiva
        para que el orquestador pueda log/skip el job con contexto.
        """
        match country:
            case Country.IN:
                return self._jiosaavn
            case Country.TW | Country.HK:
                return self._kkbox
            case Country.KR:
                return self._kkbox
            case Country.CN:
                return self._netease
            case _:
                raise UnsupportedCountryError(
                    f"AsiaDspRouter no soporta {country.value}; "
                    f"paises soportados: {sorted(c.value for c in SUPPORTED_COUNTRIES)}",
                )
