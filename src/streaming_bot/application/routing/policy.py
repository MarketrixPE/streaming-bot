"""Politica configurable del Multi-Tier Geo Router.

Concentra todos los umbrales y constantes de negocio. Los routers y
scorers dependen de esta clase, asi que cambiar un umbral no requiere
tocar logica: basta construir un nuevo ``RoutingPolicy``.

Decisiones por defecto (justificacion en docstring del campo):
- ``new_track_age_days = 7``: ventana de calentamiento previa al
  primer rollup mensual de Beatdapp/DSP.
- ``tier1_save_rate_min = 0.04``: save-rate medio post-launch en
  releases sanos (>=4 saves por cada 100 plays).
- ``tier1_skip_rate_max = 0.45``: por encima del 45% el algoritmo lo
  considera "fatigado" y baja recomendaciones.
- ``saturation_threshold = 0.8``: deja 20% de cabecera antes de
  spike-detection (Beatdapp dispara >50% sostenido pero queremos
  cushion conservador).
- ``degrade_plays_30d = 50_000`` + ``degrade_save_rate_max = 0.02``:
  track con mucho volumen y bajo engagement = vampiro de payout, lo
  bajamos a tier 3 para no quemarlo en mercados premium.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from streaming_bot.domain.routing.tier import TIER_TO_COUNTRIES, Tier
from streaming_bot.domain.value_objects import Country


def _default_max_safe_per_country() -> Mapping[Tier, int]:
    """Tope diario por pais usado para calcular ``saturation_score``.

    Tier 1 paga mas pero radar antifraude estricto: techo bajo. Tier 3
    admite mucho mas volumen porque la deteccion es laxa y el coste
    por stream es bajo.
    """
    return {
        Tier.TIER_1: 1500,
        Tier.TIER_2: 3500,
        Tier.TIER_3: 9000,
    }


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    """Umbrales que configuran el ``MultiTierGeoRouter``."""

    new_track_age_days: int = 7
    tier1_save_rate_min: float = 0.04
    tier1_skip_rate_max: float = 0.45
    saturation_threshold: float = 0.8
    degrade_plays_30d: int = 50_000
    degrade_save_rate_max: float = 0.02
    max_safe_streams_24h_by_tier: Mapping[Tier, int] = field(
        default_factory=_default_max_safe_per_country
    )

    def __post_init__(self) -> None:
        if self.new_track_age_days < 0:
            raise ValueError("new_track_age_days >=0 requerido")
        if not 0.0 <= self.tier1_save_rate_min <= 1.0:
            raise ValueError("tier1_save_rate_min fuera de rango 0..1")
        if not 0.0 <= self.tier1_skip_rate_max <= 1.0:
            raise ValueError("tier1_skip_rate_max fuera de rango 0..1")
        if self.saturation_threshold <= 0.0:
            raise ValueError("saturation_threshold debe ser >0")
        if self.degrade_plays_30d < 0:
            raise ValueError("degrade_plays_30d debe ser >=0")
        if not 0.0 <= self.degrade_save_rate_max <= 1.0:
            raise ValueError("degrade_save_rate_max fuera de rango 0..1")
        for tier, cap in self.max_safe_streams_24h_by_tier.items():
            if cap <= 0:
                raise ValueError(f"max_safe_streams_24h[{tier}] debe ser >0")

    def tier_for_country(self, country: Country) -> Tier | None:
        """Resuelve el tier al que pertenece ``country`` o ``None`` si desconocido."""
        for tier, members in TIER_TO_COUNTRIES.items():
            if country in members:
                return tier
        return None

    def max_safe_streams_24h(self, tier: Tier) -> int:
        """Tope diario por pais para el ``tier`` (usado en saturation)."""
        cap = self.max_safe_streams_24h_by_tier.get(tier)
        if cap is None:
            raise KeyError(f"sin max_safe_streams_24h para {tier}")
        return cap

    def next_less_saturated_tier(self, current: Tier) -> Tier:
        """Devuelve el siguiente tier menos saturado.

        Convencion:
        - ``TIER_1 -> TIER_2``
        - ``TIER_2 -> TIER_3``
        - ``TIER_3 -> TIER_3`` (sumidero final, no hay tier mas laxo).
        """
        if current == Tier.TIER_1:
            return Tier.TIER_2
        if current == Tier.TIER_2:
            return Tier.TIER_3
        return Tier.TIER_3
