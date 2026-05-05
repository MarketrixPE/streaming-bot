"""Planificador `PremierBoostStrategy`: convierte un gap Premier en acciones.

Toma un `PremierEligibility` y un pool de `Account`s con `country` (ya
filtradas por engagement, salud y warming). Genera un `PremierBoostPlan`
con la lista exacta de actions priorizando:

1. Plays desde territorios monetizables (US/UK/CA/AU/NZ/Nordics/EU Tier1)
   hasta cubrir `gap_monetizable_plays`. Cuentas no monetizables se
   relegan al final como camuflaje (no cuentan, pero diluyen el patron).
2. Follows desde cuentas monetizables hasta cubrir `gap_followers`.

Cada accion incluye un `delay_ms` con jitter humano (uniforme en una
ventana derivada de `min/max_jitter_ms`) para que la cadencia no sea
sub-segundo y rompa los detectores conductuales DataDome/Pex.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from streaming_bot.domain.soundcloud.monetizable_territories import is_monetizable

if TYPE_CHECKING:
    from collections.abc import Iterable

    from streaming_bot.domain.entities import Account
    from streaming_bot.domain.soundcloud.models import PremierEligibility


class PremierBoostType(str, Enum):
    """Tipo de accion que el plan puede emitir."""

    PLAY = "play"
    FOLLOW = "follow"


@dataclass(frozen=True, slots=True)
class PremierBoostAction:
    """Una accion concreta a ejecutar contra el track/owner.

    `delay_ms` es el delay HUMANO antes de iniciar la accion. La strategy
    Patchright lo respeta usando `IRichBrowserSession.wait()` o el
    `DecisionDelayPolicy` correspondiente.
    """

    account_id: str
    country: str
    action: PremierBoostType
    target_urn: str
    delay_ms: int
    monetizable: bool


@dataclass(frozen=True, slots=True)
class PremierBoostPlan:
    """Plan completo: lista ordenada de actions + metadatos del gap."""

    track_urn: str
    gap_followers: int
    gap_monetizable_plays: int
    actions: tuple[PremierBoostAction, ...] = field(default_factory=tuple)

    @property
    def total_actions(self) -> int:
        return len(self.actions)

    @property
    def monetizable_play_actions(self) -> int:
        return sum(
            1
            for a in self.actions
            if a.action is PremierBoostType.PLAY and a.monetizable
        )

    @property
    def follow_actions(self) -> int:
        return sum(1 for a in self.actions if a.action is PremierBoostType.FOLLOW)


class PremierBoostStrategy:
    """Planifica el camino mas corto desde `PremierEligibility` hasta elegibilidad.

    El planner es DETERMINISTA si se inyecta `rng_seed`: misma seed +
    misma entrada => mismo plan. Esto facilita los tests.
    """

    def __init__(
        self,
        *,
        min_jitter_ms: int = 1500,
        max_jitter_ms: int = 9000,
        rng_seed: int | None = None,
    ) -> None:
        if min_jitter_ms < 0:
            raise ValueError("min_jitter_ms debe ser >= 0")
        if max_jitter_ms < min_jitter_ms:
            raise ValueError("max_jitter_ms debe ser >= min_jitter_ms")
        self._min_jitter_ms = min_jitter_ms
        self._max_jitter_ms = max_jitter_ms
        # Random aislado: misma seed => mismas trayectorias en tests.
        self._rng = random.Random(rng_seed) if rng_seed is not None else random.Random()  # noqa: S311

    def plan(
        self,
        *,
        eligibility: PremierEligibility,
        accounts_pool: Iterable[Account],
    ) -> PremierBoostPlan:
        """Construye el `PremierBoostPlan` para cerrar el gap.

        Algoritmo:
        1. Particiona el pool en monetizable / non-monetizable segun el
           `country` de cada `Account`.
        2. Asigna primero plays de cuentas monetizables hasta cubrir
           `gap_monetizable_plays`. Cuentas no monetizables se usan como
           camuflaje SOLO si quedan slots de play tras el cap monetizable
           y el gap ya esta cubierto (mantiene la huella diversa sin
           inflar la metric falsa).
        3. Asigna follows desde cuentas monetizables hasta cubrir
           `gap_followers`. Si se acaban, completa con no-monetizables
           (los follows cuentan independientemente del territorio).
        4. Cada cuenta se usa MAXIMO una vez por accion para no replay
           jobs en la misma sesion (defensa antifraude trivial).
        """
        if eligibility.is_eligible:
            return PremierBoostPlan(
                track_urn=eligibility.track_urn,
                gap_followers=0,
                gap_monetizable_plays=0,
            )

        monetizable_pool, non_monetizable_pool = _partition_pool(accounts_pool)

        actions: list[PremierBoostAction] = []
        used_for_play: set[str] = set()
        used_for_follow: set[str] = set()

        # 1. Plays monetizables (los unicos que cuentan para el threshold).
        play_quota = eligibility.gap_monetizable_plays
        for account in monetizable_pool:
            if play_quota == 0:
                break
            actions.append(
                PremierBoostAction(
                    account_id=account.id,
                    country=account.country.value,
                    action=PremierBoostType.PLAY,
                    target_urn=eligibility.track_urn,
                    delay_ms=self._jitter_ms(),
                    monetizable=True,
                ),
            )
            used_for_play.add(account.id)
            play_quota -= 1

        # 2. Follows: monetizable primero (mas valioso por geo), luego
        # completa con non-monetizable hasta cubrir el threshold. Una
        # cuenta NUNCA puede ejecutar play + follow en la misma sesion:
        # repetir genera huella conductual trivial de detectar (Pex).
        follow_quota = eligibility.gap_followers
        for pool, monetizable in (
            (monetizable_pool, True),
            (non_monetizable_pool, False),
        ):
            for account in pool:
                if follow_quota == 0:
                    break
                if account.id in used_for_follow or account.id in used_for_play:
                    continue
                actions.append(
                    PremierBoostAction(
                        account_id=account.id,
                        country=account.country.value,
                        action=PremierBoostType.FOLLOW,
                        target_urn=eligibility.track_urn,
                        delay_ms=self._jitter_ms(),
                        monetizable=monetizable,
                    ),
                )
                used_for_follow.add(account.id)
                follow_quota -= 1

        return PremierBoostPlan(
            track_urn=eligibility.track_urn,
            gap_followers=eligibility.gap_followers,
            gap_monetizable_plays=eligibility.gap_monetizable_plays,
            actions=tuple(actions),
        )

    def _jitter_ms(self) -> int:
        """Devuelve un delay humano uniforme en la ventana configurada."""
        return self._rng.randint(self._min_jitter_ms, self._max_jitter_ms)


def _partition_pool(accounts: Iterable[Account]) -> tuple[list[Account], list[Account]]:
    """Particiona el pool en (monetizables, no-monetizables).

    El orden relativo se preserva: el caller suele entregar el pool ya
    barajado / ordenado por warming. La estrategia no debe re-ordenarlo
    para no romper la idempotencia que el caller puede asumir.
    """
    monetizable: list[Account] = []
    non_monetizable: list[Account] = []
    for account in accounts:
        if not account.status.is_usable:
            continue
        if is_monetizable(account.country):
            monetizable.append(account)
        else:
            non_monetizable.append(account)
    return monetizable, non_monetizable
