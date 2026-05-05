"""Politica de distribucion: cuantos distros, cuanta concentracion permitida.

Resumen de invariantes:
- min_distributors: cota inferior de redundancia (default 2 para v1).
- max_concentration_pct: porcentaje maximo del catalogo total que un mismo
  distribuidor puede contener. Si superaria el cap, el use case lo descarta.
- alias_pool: pool ordenado de adjetivos+sustantivos para sintetizar aliases
  cuando el alias_resolver no encuentra uno persistido.
- retry_takedown_threshold: numero de takedowns sufridos por un distribuidor
  antes de marcarlo como "no usar de nuevo".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from streaming_bot.domain.distribution.distributor_id import DistributorId

# Pool default usado cuando el caller no pasa uno propio. Las palabras evitan
# colisiones con marcas registradas y se mantienen en ingles para coherencia
# con catalogo internacional.
_DEFAULT_ADJECTIVES: tuple[str, ...] = (
    "Cosmic",
    "Velvet",
    "Crystal",
    "Midnight",
    "Electric",
    "Lunar",
    "Solar",
    "Neon",
    "Ember",
    "Glacier",
    "Coral",
    "Iron",
    "Silent",
    "Wild",
    "Phantom",
    "Northern",
    "Southern",
    "Ancient",
    "Modern",
    "Echo",
)

_DEFAULT_NOUNS: tuple[str, ...] = (
    "Beats",
    "Vibes",
    "Wave",
    "Sound",
    "Soul",
    "Frequency",
    "Pulse",
    "Garden",
    "Skyline",
    "Drift",
    "Echo",
    "Bloom",
    "Ritual",
    "Theory",
    "Project",
    "Atlas",
    "Society",
    "Movement",
    "Lab",
    "Codex",
)


@dataclass(frozen=True, slots=True)
class DispatchPolicy:
    """Politica del orquestador de dispatch.

    `alias_pool_per_distributor` permite reservar adjetivos/sustantivos
    distintos por distribuidor (mas defensa anti-correlacion). Si esta vacio,
    se usa el pool default por distribuidor.
    """

    min_distributors: int = 2
    max_concentration_pct: float = 0.25
    retry_takedown_threshold: int = 2
    label_name: str = "Worldwide Hits"
    alias_adjective_pool: tuple[str, ...] = field(default_factory=lambda: _DEFAULT_ADJECTIVES)
    alias_noun_pool: tuple[str, ...] = field(default_factory=lambda: _DEFAULT_NOUNS)
    alias_pool_per_distributor: dict[DistributorId, tuple[str, ...]] = field(default_factory=dict)
    excluded_distributors: frozenset[DistributorId] = field(default_factory=frozenset)
    rng_seed: int | None = None

    def __post_init__(self) -> None:
        if self.min_distributors < 1:
            raise ValueError("min_distributors debe ser >= 1")
        if not 0.0 < self.max_concentration_pct <= 1.0:
            raise ValueError("max_concentration_pct debe estar en (0, 1]")
        if self.retry_takedown_threshold < 1:
            raise ValueError("retry_takedown_threshold debe ser >= 1")
        if not self.alias_adjective_pool or not self.alias_noun_pool:
            raise ValueError("alias_adjective_pool y alias_noun_pool no pueden estar vacios")

    def alias_pool_for(self, distributor: DistributorId) -> tuple[str, ...]:
        """Devuelve el pool dedicado al distribuidor (si existe) o cadena vacia."""
        return self.alias_pool_per_distributor.get(distributor, ())
