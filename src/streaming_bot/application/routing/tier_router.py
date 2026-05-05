"""``MultiTierGeoRouter``: decide a que tier asignar cada track.

Aplica las reglas del proyecto en orden estricto y delega umbrales y
mappings a ``RoutingPolicy``. Sin I/O: recibe un ``TrackHealthScore``
ya calculado y devuelve el tier.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from streaming_bot.application.routing.policy import RoutingPolicy
from streaming_bot.domain.routing.tier import Tier
from streaming_bot.domain.routing.track_health import TrackHealthScore

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

    from streaming_bot.domain.song import Song


class MultiTierGeoRouter:
    """Router multi-tier basado en salud del track.

    Reglas (orden):
    1. Edad < ``new_track_age_days`` -> ``TIER_3`` (calentamiento puro,
       sin rotacion por saturacion: el track es nuevo, todavia no
       puede saturar nada).
    2. ``plays_30d > degrade_plays_30d`` y ``save_rate < degrade_save_rate_max``
       -> ``TIER_3`` (degradar para no quemar payout en premium).
    3. ``save_rate >= tier1_save_rate_min`` y ``skip_rate < tier1_skip_rate_max``
       -> ``TIER_1`` (candidato monetizable).
    4. Resto -> ``TIER_2`` (default).
    5. Si ``saturation_score > saturation_threshold`` y la edad supera
       el umbral de "nuevo", rotamos al siguiente tier menos saturado.
    """

    def __init__(
        self,
        *,
        policy: RoutingPolicy | None = None,
        logger: BoundLogger | None = None,
    ) -> None:
        self._policy = policy if policy is not None else RoutingPolicy()
        self._log = (
            logger.bind(component="tier_router") if logger is not None else None
        )

    @property
    def policy(self) -> RoutingPolicy:
        return self._policy

    def pick_tier(self, *, track: Song, score: TrackHealthScore) -> Tier:
        """Decide el tier optimo para ``track`` segun ``score``.

        Args:
            track: cancion target a enrutar (se usa solo para logging).
            score: snapshot de salud reciente del track.

        Returns:
            Tier elegido segun las reglas configuradas.
        """
        decision = self._apply_rules(score)
        if self._log is not None:
            self._log.debug(
                "tier_router.decision",
                song_id=track.spotify_uri,
                tier=decision.value,
                age_days=score.age_days,
                save_rate=score.save_rate,
                skip_rate=score.skip_rate,
                plays_30d=score.plays_30d,
                saturation=score.saturation_score,
            )
        return decision

    def _apply_rules(self, score: TrackHealthScore) -> Tier:
        policy = self._policy

        # Regla 1: tracks recientes van directo a TIER_3 sin rotacion.
        if score.age_days < policy.new_track_age_days:
            return Tier.TIER_3

        # Regla 2: degradacion forzada cuando hay volumen sin engagement.
        if (
            score.plays_30d > policy.degrade_plays_30d
            and score.save_rate < policy.degrade_save_rate_max
        ):
            return Tier.TIER_3

        # Regla 3: candidato monetizable.
        if (
            score.save_rate >= policy.tier1_save_rate_min
            and score.skip_rate < policy.tier1_skip_rate_max
        ):
            candidate = Tier.TIER_1
        else:
            candidate = Tier.TIER_2

        # Regla 5: rotacion por saturacion (solo aplica para edad >= umbral).
        if score.saturation_score > policy.saturation_threshold:
            candidate = policy.next_less_saturated_tier(candidate)
        return candidate
