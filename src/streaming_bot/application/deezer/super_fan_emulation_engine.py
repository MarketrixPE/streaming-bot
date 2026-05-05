"""Engine que planifica sesiones super-fan organicas para Deezer.

Reglas que la sesion debe satisfacer (ACPS-friendly):
1. Duracion total >= `min_session_minutes` (default 45min).
2. El track objetivo aparece entre 1 y 2 veces (replay incluido).
3. Al menos un 60% del tiempo se gasta escuchando OTROS artistas seguidos
   por la cuenta (catalogo amplio, no monomania artificial).
4. Hay jitter entre tracks (3-15s) que emula el "tiempo entre canciones"
   de un humano real navegando.

El engine es PURO (sin I/O, sin asyncio): recibe pools precomputados y
devuelve un `PlannedSession`. La ejecucion (clicks, esperas) la hace
`DeezerStrategy` en presentation/.

Determinismo: pasando `rng_seed` se reproducen los planes exactos en tests.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from random import Random


@dataclass(frozen=True, slots=True)
class TrackCandidate:
    """Track elegible para entrar en la sesion (target, relleno, etc.).

    `duration_seconds` es importante: el engine usa duraciones reales para
    calcular cuantos tracks meter en la sesion. Si la fuente no la conoce,
    pasar un default conservador (~210s).
    """

    uri: str
    artist_uri: str
    duration_seconds: int

    def __post_init__(self) -> None:
        # Tracks de duracion <= 30s no son escuchas validas en Deezer; el
        # engine las rechaza para evitar planes degenerados.
        if self.duration_seconds <= 30:
            raise ValueError(
                f"duration_seconds debe ser > 30s para ser super-fan-able: "
                f"{self.duration_seconds}"
            )


@dataclass(frozen=True, slots=True)
class PlannedTrackPlay:
    """Item del plan: un track concreto a reproducir con su jitter previo."""

    track_uri: str
    artist_uri: str
    listen_seconds: int
    pre_jitter_seconds: int
    is_target: bool
    is_replay: bool


@dataclass(frozen=True, slots=True)
class PlannedSession:
    """Plan inmutable de la sesion super-fan."""

    target_track_uri: str
    plays: tuple[PlannedTrackPlay, ...] = field(default_factory=tuple)

    @property
    def total_listen_seconds(self) -> int:
        """Suma de duraciones de escucha (sin jitter)."""
        return sum(play.listen_seconds for play in self.plays)

    @property
    def total_jitter_seconds(self) -> int:
        return sum(play.pre_jitter_seconds for play in self.plays)

    @property
    def total_seconds(self) -> int:
        """Duracion total prevista de la sesion (escucha + jitter)."""
        return self.total_listen_seconds + self.total_jitter_seconds

    @property
    def total_minutes(self) -> float:
        return self.total_seconds / 60.0

    @property
    def target_play_count(self) -> int:
        return sum(1 for p in self.plays if p.is_target)

    @property
    def filler_listen_seconds(self) -> int:
        """Segundos que se gastan en tracks que NO son el objetivo."""
        return sum(p.listen_seconds for p in self.plays if not p.is_target)

    @property
    def filler_ratio(self) -> float:
        """Fraccion del tiempo que se dedica a relleno (otros artistas)."""
        total = self.total_listen_seconds
        if total <= 0:
            return 0.0
        return self.filler_listen_seconds / total


# Constantes de planificacion. Documentadas in-line; cambiar requiere
# revisar pruebas de `test_super_fan_emulation`.
_MIN_JITTER_SECONDS = 3
_MAX_JITTER_SECONDS = 15
_MIN_FILLER_RATIO = 0.6
_MAX_TARGET_PLAYS = 2
_MIN_TARGET_PLAYS = 1
# Limite duro para evitar bucles infinitos si los pools son raros.
_MAX_PLAN_ITERATIONS = 200


class SuperFanEmulationEngine:
    """Planificador deterministico de sesiones super-fan.

    Uso tipico:
        engine = SuperFanEmulationEngine(rng_seed=42)
        plan = engine.plan_session(
            target_track=target,
            target_artist_pool=other_target_artist_tracks,
            followed_artists_pool=other_followed_artists_tracks,
        )
    """

    def __init__(
        self,
        *,
        rng_seed: int | None = None,
        min_session_minutes: int = 45,
        min_filler_ratio: float = _MIN_FILLER_RATIO,
    ) -> None:
        # `Random` (no `SystemRandom`): no es seguridad criptografica, es
        # variacion conductual reproducible.
        self._rng = Random(rng_seed) if rng_seed is not None else Random()  # noqa: S311
        if min_session_minutes <= 0:
            raise ValueError(f"min_session_minutes debe ser > 0: {min_session_minutes}")
        if not 0.0 <= min_filler_ratio <= 1.0:
            raise ValueError(f"min_filler_ratio fuera de [0, 1]: {min_filler_ratio}")
        self._min_session_seconds = min_session_minutes * 60
        self._min_filler_ratio = min_filler_ratio

    def plan_session(
        self,
        *,
        target_track: TrackCandidate,
        target_artist_pool: Sequence[TrackCandidate] = (),
        followed_artists_pool: Sequence[TrackCandidate] = (),
    ) -> PlannedSession:
        """Construye un `PlannedSession` que cumple las reglas ACPS-friendly.

        Args:
            target_track: el track que queremos boostear.
            target_artist_pool: otras canciones del MISMO artista del target
                (5-10 son habituales; si esta vacio se omite ese segmento).
            followed_artists_pool: tracks de OTROS artistas que la cuenta ya
                sigue. Es la fuente principal de "naturalidad".

        Returns:
            `PlannedSession` con plays totalizando >= min_session_minutes y
            con el target apareciendo 1-2 veces (replay).

        Raises:
            ValueError: si `followed_artists_pool` esta vacio (no se puede
                construir una sesion super-fan creible solo con un artista).
        """
        if not followed_artists_pool:
            raise ValueError(
                "followed_artists_pool no puede estar vacio: una sesion "
                "super-fan exige relleno de otros artistas seguidos"
            )

        plays: list[PlannedTrackPlay] = []

        # 1) Empezar con 1-2 tracks de relleno para que la sesion no abra
        #    directamente con el target (patron clasico de bot).
        prelude_count = self._rng.randint(1, 2)
        for _ in range(prelude_count):
            plays.append(self._make_play(self._pick(followed_artists_pool), is_target=False))

        # 2) Insertar el target con replay opcional (1-2 plays).
        target_plays = self._rng.randint(_MIN_TARGET_PLAYS, _MAX_TARGET_PLAYS)
        for idx in range(target_plays):
            plays.append(self._make_play(target_track, is_target=True, is_replay=idx > 0))
            # Tras el target, un track del MISMO artista (5-10 random) para
            # parecer un super-fan navegando por el catalogo del artista.
            if target_artist_pool:
                plays.append(
                    self._make_play(self._pick(target_artist_pool), is_target=False)
                )

        # 3) Rellenar hasta cumplir min_session_seconds y filler_ratio,
        #    alternando followed_artists_pool con un poco de target_artist_pool
        #    para mantener naturalidad. Limitamos el bucle por seguridad.
        iterations = 0
        while iterations < _MAX_PLAN_ITERATIONS:
            iterations += 1
            current = sum(p.listen_seconds for p in plays) + sum(
                p.pre_jitter_seconds for p in plays
            )
            if current >= self._min_session_seconds:
                # Al cumplir duracion, garantizamos tambien filler_ratio.
                listen_total = sum(p.listen_seconds for p in plays)
                filler_total = sum(p.listen_seconds for p in plays if not p.is_target)
                if listen_total <= 0 or (filler_total / listen_total) >= self._min_filler_ratio:
                    break

            # Eleccion ponderada: 80% otros artistas seguidos, 20% mismo
            # artista del target (si hay pool). Promueve diversidad.
            if target_artist_pool and self._rng.random() < 0.2:
                plays.append(self._make_play(self._pick(target_artist_pool), is_target=False))
            else:
                plays.append(self._make_play(self._pick(followed_artists_pool), is_target=False))

        return PlannedSession(
            target_track_uri=target_track.uri,
            plays=tuple(plays),
        )

    # ── Helpers internos ──────────────────────────────────────────────────
    def _pick(self, pool: Sequence[TrackCandidate]) -> TrackCandidate:
        """Elige un candidato uniformemente del pool. Asume pool no-vacio."""
        idx = self._rng.randrange(0, len(pool))
        return pool[idx]

    def _make_play(
        self,
        track: TrackCandidate,
        *,
        is_target: bool,
        is_replay: bool = False,
    ) -> PlannedTrackPlay:
        """Construye un `PlannedTrackPlay` con jitter humano y duracion realista.

        Para tracks completos elegimos escuchar el 80%-100% de su duracion;
        humanos rara vez consumen el 100% exacto (skips, fades).
        """
        # 80%-100% de la duracion total. floor para evitar 100% exacto.
        listen_factor = self._rng.uniform(0.8, 1.0)
        listen_seconds = max(35, math.floor(track.duration_seconds * listen_factor))
        jitter = self._rng.randint(_MIN_JITTER_SECONDS, _MAX_JITTER_SECONDS)
        return PlannedTrackPlay(
            track_uri=track.uri,
            artist_uri=track.artist_uri,
            listen_seconds=listen_seconds,
            pre_jitter_seconds=jitter,
            is_target=is_target,
            is_replay=is_replay,
        )
