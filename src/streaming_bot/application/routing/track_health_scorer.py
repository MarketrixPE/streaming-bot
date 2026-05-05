"""Calcula ``TrackHealthScore`` desde streams + behaviors recientes.

El scorer es puro: recibe historial ya hidratado, conteo de saves y
streams_24h por geo y devuelve el snapshot. La capa infra
(``ClickhouseTrackHealthRepository``) se encarga de poblar esos
inputs desde ClickHouse.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from streaming_bot.application.routing.policy import RoutingPolicy
from streaming_bot.domain.history import StreamHistory, StreamOutcome
from streaming_bot.domain.routing.track_health import TrackHealthScore

if TYPE_CHECKING:
    from streaming_bot.domain.song import Song
    from streaming_bot.domain.value_objects import Country


class TrackHealthScorer:
    """Construye ``TrackHealthScore`` a partir del historial.

    Reglas:
    - ``age_days``: ``as_of.date() - song.metadata.release_date``,
      saturado a 0 si la cancion aun no tiene release_date.
    - ``plays_30d``: count de outcomes ``COUNTED`` en las ultimas
      30d. Filtramos por ``song_uri`` defensivamente.
    - ``skip_rate``: ``SKIPPED`` / total_intentos en 30d (excluye
      ``PENDING`` para no contaminar denominador).
    - ``save_rate``: ``saves_count / max(plays_30d, 1)`` truncado a
      1.0 (saves > plays es teorico cuando el catalogo recoge saves
      historicos pero plays es solo 30d).
    - ``saturation_score``: ``max`` sobre paises del ratio
      ``streams_24h[country] / max_safe_24h(tier_de_country)``.
    """

    def __init__(self, *, policy: RoutingPolicy | None = None) -> None:
        self._policy = policy if policy is not None else RoutingPolicy()

    def score(
        self,
        *,
        song: Song,
        histories: Sequence[StreamHistory],
        saves_count: int,
        streams_24h_by_country: Mapping[Country, int] | None = None,
        as_of: datetime,
    ) -> TrackHealthScore:
        """Calcula el snapshot de salud para la fecha ``as_of``.

        Args:
            song: cancion target (necesaria para release_date).
            histories: historial de streams (puede contener otras
                canciones; se filtra por ``song_uri``).
            saves_count: total de saves observados en 30d.
            streams_24h_by_country: streams ``counted`` por pais en las
                ultimas 24h. ``None`` o vacio implica saturacion 0.
            as_of: instante de referencia ("ahora" en UTC).
        """
        if saves_count < 0:
            raise ValueError("saves_count >=0 requerido")

        age_days = self._age_days(song, as_of)
        plays_30d, skip_rate = self._plays_and_skip_rate(
            histories,
            song_uri=song.spotify_uri,
            cutoff=as_of - timedelta(days=30),
        )
        save_rate = min(saves_count / plays_30d, 1.0) if plays_30d > 0 else 0.0
        saturation = self._saturation(streams_24h_by_country or {})

        return TrackHealthScore(
            age_days=age_days,
            plays_30d=plays_30d,
            save_rate=save_rate,
            skip_rate=skip_rate,
            saturation_score=saturation,
            computed_at=as_of,
        )

    @staticmethod
    def _age_days(song: Song, as_of: datetime) -> int:
        """Calcula la edad del track en dias completos."""
        release = song.metadata.release_date
        if release is None:
            return 0
        delta = as_of.date() - release
        return max(delta.days, 0)

    @staticmethod
    def _plays_and_skip_rate(
        histories: Sequence[StreamHistory],
        *,
        song_uri: str,
        cutoff: datetime,
    ) -> tuple[int, float]:
        """Recorre histories una vez calculando plays_30d y skip_rate."""
        plays_30d = 0
        skipped = 0
        attempts = 0
        for history in histories:
            if history.song_uri != song_uri:
                continue
            if history.occurred_at < cutoff:
                continue
            if history.outcome == StreamOutcome.PENDING:
                continue
            attempts += 1
            if history.outcome == StreamOutcome.COUNTED:
                plays_30d += 1
            elif history.outcome == StreamOutcome.SKIPPED:
                skipped += 1
        skip_rate = skipped / attempts if attempts > 0 else 0.0
        return plays_30d, skip_rate

    def _saturation(self, streams_24h_by_country: Mapping[Country, int]) -> float:
        """Saturacion = max sobre paises de streams_24h / max_safe."""
        if not streams_24h_by_country:
            return 0.0
        max_sat = 0.0
        for country, streams in streams_24h_by_country.items():
            tier = self._policy.tier_for_country(country)
            if tier is None:
                continue
            max_safe = self._policy.max_safe_streams_24h(tier)
            ratio = streams / max_safe
            max_sat = max(max_sat, ratio)
        return max_sat
