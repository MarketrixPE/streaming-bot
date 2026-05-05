"""Catalogo de distribuidores soportados y su economia anual.

Las tarifas son aproximaciones publicas Q1 2026. Sirven al optimizador del
DispatchPolicy para preferir distribuidores con mejor coste / track / ano
cuando hay empates en concentracion.

Notas:
- DistroKid: subscripcion anual unlimited (Musician $22.99). Coste por track
  amortizado depende del catalogo; usamos 0.50 USD/track/ano como estimacion
  conservadora para ~50 tracks/ano.
- RouteNote: plan Free (15% revenue cut) o Premium (~9.99 USD/ano unlimited).
  Como modelo el coste por track del plan free como 0 (revenue share).
- Amuse: Free tier sin limite de uploads. Boost (paid) = 24.99/year.
- Stem: revenue share 5%, sin coste fijo.
- TuneCore: $9.99/single + $0/year a partir del 2do ano.
- IDOL: solo via contrato con sello, no aplica per-track.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DistributorId(str, Enum):
    """Distribuidores soportados por el dispatcher v1."""

    DISTROKID = "distrokid"
    ROUTENOTE = "routenote"
    AMUSE = "amuse"
    STEM = "stem"
    TUNECORE = "tunecore"
    IDOL = "idol"


@dataclass(frozen=True, slots=True)
class DistributorEconomics:
    """Economia simplificada de un distribuidor.

    - annual_fee_per_track_usd: coste estimado por track al ano (subscripcion
      amortizada o tarifa per-release dividida entre el catalogo medio).
    - revenue_share_pct: porcentaje del revenue que retiene el distribuidor.
    - has_public_api: si expone HTTP API publica (afecta el tipo de adapter
      que usaremos: HTTP nativo vs scraping browser).
    """

    distributor: DistributorId
    annual_fee_per_track_usd: float
    revenue_share_pct: float
    has_public_api: bool


_ECONOMICS: dict[DistributorId, DistributorEconomics] = {
    DistributorId.DISTROKID: DistributorEconomics(
        distributor=DistributorId.DISTROKID,
        annual_fee_per_track_usd=0.50,
        revenue_share_pct=0.0,
        has_public_api=False,
    ),
    DistributorId.ROUTENOTE: DistributorEconomics(
        distributor=DistributorId.ROUTENOTE,
        annual_fee_per_track_usd=0.0,
        revenue_share_pct=15.0,
        has_public_api=True,
    ),
    DistributorId.AMUSE: DistributorEconomics(
        distributor=DistributorId.AMUSE,
        annual_fee_per_track_usd=0.0,
        revenue_share_pct=0.0,
        has_public_api=False,
    ),
    DistributorId.STEM: DistributorEconomics(
        distributor=DistributorId.STEM,
        annual_fee_per_track_usd=0.0,
        revenue_share_pct=5.0,
        has_public_api=True,
    ),
    DistributorId.TUNECORE: DistributorEconomics(
        distributor=DistributorId.TUNECORE,
        annual_fee_per_track_usd=9.99,
        revenue_share_pct=0.0,
        has_public_api=False,
    ),
    DistributorId.IDOL: DistributorEconomics(
        distributor=DistributorId.IDOL,
        annual_fee_per_track_usd=0.0,
        revenue_share_pct=15.0,
        has_public_api=False,
    ),
}


def distributor_economics(distributor: DistributorId) -> DistributorEconomics:
    """Devuelve la economia conocida del distribuidor."""
    return _ECONOMICS[distributor]
