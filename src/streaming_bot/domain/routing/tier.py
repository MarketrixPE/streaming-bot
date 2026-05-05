"""Tiers de routing geografico.

- ``TIER_1``: mercados anglosajones + nordicos (alto payout por stream,
  pero radar antifraude estricto). Reservado a tracks "monetizables".
- ``TIER_2``: EU continental + LATAM premium + JP (payout medio,
  volumen sostenido, deteccion media).
- ``TIER_3``: high-volume / discovery / mercados de bajo payout
  (LATAM expansiva, Asia/SEA emergente). Util para calentar tracks
  nuevos sin afectar metricas premium ni quemar payout.

Notas:
- IN/ID/PH/VN no estan todavia en ``Country`` por lo que los proxys
  high-volume se cubren con BR + LATAM secundaria + TH. Cuando se
  amplie el enum, basta extender ``TIER_TO_COUNTRIES``.
"""

from __future__ import annotations

from enum import Enum

from streaming_bot.domain.value_objects import Country


class Tier(str, Enum):
    """Tier de payout/volumen para enrutar streams."""

    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


# Mapping tier -> conjunto de paises representativos. Cada pais aparece
# en exactamente un tier (invariante validado por tests).
TIER_TO_COUNTRIES: dict[Tier, frozenset[Country]] = {
    Tier.TIER_1: frozenset(
        {
            Country.US,
            Country.GB,
            Country.AU,
            Country.NZ,
            Country.CA,
            Country.IE,
            Country.SE,
            Country.NO,
            Country.DK,
            Country.FI,
        }
    ),
    Tier.TIER_2: frozenset(
        {
            Country.DE,
            Country.FR,
            Country.IT,
            Country.ES,
            Country.PT,
            Country.NL,
            Country.AT,
            Country.BE,
            Country.CH,
            Country.JP,
            Country.MX,
            Country.AR,
            Country.CL,
            Country.CO,
            Country.PE,
        }
    ),
    Tier.TIER_3: frozenset(
        {
            Country.BR,
            Country.TH,
            Country.EC,
            Country.BO,
            Country.DO,
            Country.PR,
            Country.VE,
            Country.UY,
            Country.PY,
            Country.PA,
            Country.GT,
            Country.HN,
            Country.SV,
            Country.NI,
            Country.CR,
        }
    ),
}
