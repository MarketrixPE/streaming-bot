"""Distribucion territorial objetivo del trafico generado.

Estrategia post-Oct'25 (Camino A):
- 90 dias cooling-off UK/CH = 0%.
- Mercados core LATAM con presencia organica previa.
- Reintroduccion gradual UK/CH en mes 4 (5%) y mes 6 (10%).

El `TerritoryDistribution` es un value object inmutable que el scheduler
usa para repartir streams diarios entre proxies/modems por pais.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from streaming_bot.domain.value_objects import Country


@dataclass(frozen=True, slots=True)
class TerritoryWeight:
    """Peso porcentual asignado a un pais en una distribucion."""

    country: Country
    weight: float  # 0.0 - 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"weight fuera de rango: {self.weight}")


@dataclass(frozen=True, slots=True)
class TerritoryDistribution:
    """Distribucion porcentual de streams por pais.

    Invariante: la suma de pesos no debe exceder 1.0 (puede ser <1.0 si
    hay un porcentaje "direct" sin proxy de pais especifico).
    """

    weights: tuple[TerritoryWeight, ...]
    label: str  # "phase-1-latam-only" | "phase-2-mixed" | "phase-3-balanced"

    def __post_init__(self) -> None:
        total = sum(w.weight for w in self.weights)
        if total > 1.0001:
            raise ValueError(f"suma de pesos excede 1.0: {total}")
        countries = [w.country for w in self.weights]
        if len(countries) != len(set(countries)):
            raise ValueError("paises duplicados en distribucion")

    def weight_of(self, country: Country) -> float:
        """Devuelve el peso asignado a un pais o 0 si no esta presente."""
        for w in self.weights:
            if w.country == country:
                return w.weight
        return 0.0

    def includes(self, country: Country) -> bool:
        """¿Este pais esta en la distribucion con peso > 0?"""
        return self.weight_of(country) > 0.0

    def total_weight(self) -> float:
        return sum(w.weight for w in self.weights)


class TerritoryPlan:
    """Plan temporal de distribuciones territoriales segun fase del ramp-up."""

    PHASE_1_LATAM_ONLY = TerritoryDistribution(
        label="phase-1-latam-only",
        weights=(
            TerritoryWeight(Country.PE, 0.30),
            TerritoryWeight(Country.MX, 0.20),
            TerritoryWeight(Country.US, 0.15),  # hispano
            TerritoryWeight(Country.ES, 0.12),
            TerritoryWeight(Country.CL, 0.08),
            TerritoryWeight(Country.AR, 0.05),
            TerritoryWeight(Country.CO, 0.04),
            TerritoryWeight(Country.EC, 0.03),
            TerritoryWeight(Country.BO, 0.02),
            TerritoryWeight(Country.DO, 0.01),
        ),
    )

    PHASE_2_MIXED = TerritoryDistribution(
        label="phase-2-mixed",
        weights=(
            TerritoryWeight(Country.PE, 0.22),
            TerritoryWeight(Country.MX, 0.16),
            TerritoryWeight(Country.US, 0.13),
            TerritoryWeight(Country.ES, 0.10),
            TerritoryWeight(Country.CL, 0.07),
            TerritoryWeight(Country.AR, 0.05),
            TerritoryWeight(Country.CO, 0.04),
            TerritoryWeight(Country.GB, 0.10),  # reintroduccion UK
            TerritoryWeight(Country.IT, 0.04),
            TerritoryWeight(Country.FR, 0.03),
            TerritoryWeight(Country.DE, 0.03),
            TerritoryWeight(Country.PT, 0.02),
            TerritoryWeight(Country.EC, 0.01),
        ),
    )

    PHASE_3_BALANCED = TerritoryDistribution(
        label="phase-3-balanced",
        weights=(
            TerritoryWeight(Country.PE, 0.16),
            TerritoryWeight(Country.MX, 0.12),
            TerritoryWeight(Country.US, 0.12),
            TerritoryWeight(Country.GB, 0.15),  # UK normalizado
            TerritoryWeight(Country.ES, 0.10),
            TerritoryWeight(Country.DE, 0.06),
            TerritoryWeight(Country.FR, 0.05),
            TerritoryWeight(Country.IT, 0.05),
            TerritoryWeight(Country.CH, 0.04),  # CH suave
            TerritoryWeight(Country.NL, 0.03),
            TerritoryWeight(Country.CL, 0.04),
            TerritoryWeight(Country.AR, 0.03),
            TerritoryWeight(Country.CO, 0.02),
            TerritoryWeight(Country.PT, 0.02),
            TerritoryWeight(Country.SE, 0.01),
        ),
    )

    @classmethod
    def for_day(cls, day_offset: int) -> TerritoryDistribution:
        """Selecciona la distribucion segun el dia del programa.

        - dia 0-89  -> PHASE_1_LATAM_ONLY (cooling-off UK/CH absoluto)
        - dia 90-149 -> PHASE_2_MIXED (UK reintroducido suave)
        - dia 150+  -> PHASE_3_BALANCED (UK + CH normalizados)
        """
        if day_offset < 90:
            return cls.PHASE_1_LATAM_ONLY
        if day_offset < 150:
            return cls.PHASE_2_MIXED
        return cls.PHASE_3_BALANCED

    @classmethod
    def for_date(cls, today: date, program_start: date) -> TerritoryDistribution:
        return cls.for_day((today - program_start).days)
