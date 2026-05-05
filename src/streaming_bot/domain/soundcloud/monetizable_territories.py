"""Territorios monetizables para SoundCloud Premier (Q1 2026).

SoundCloud paga regalias unicamente por plays originados en estos paises.
La lista refleja los mercados con royalty pool activo (US, UK, Tier-1 EU
+ ANZ + Nordics) segun el contrato Premier vigente Q1 2026. Si un play no
proviene de un pais aqui listado, NO cuenta para el threshold de 1000
plays/30d necesario para entrar al programa.

La frozenset es inmutable: cualquier cambio editorial (p.ej. apertura de
LATAM) requiere un commit explicito y revisar `PremierBoostStrategy` y
los tests asociados.
"""

from __future__ import annotations

from streaming_bot.domain.value_objects import Country

MONETIZABLE_TERRITORIES: frozenset[Country] = frozenset(
    {
        Country.US,
        Country.GB,
        Country.CA,
        Country.AU,
        Country.NZ,
        Country.IE,
        Country.SE,
        Country.NO,
        Country.DK,
        Country.FI,
        Country.DE,
        Country.FR,
        Country.NL,
    },
)


def is_monetizable(country: Country) -> bool:
    """Devuelve True si los plays desde `country` cuentan para Premier."""
    return country in MONETIZABLE_TERRITORIES
