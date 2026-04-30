"""Compositor de playlists con mezcla target+camuflaje determinista.

Implementa `IPlaylistComposer` con anti-contiguidad de targets, ratio configurable,
y estrategia de intercalado que simula comportamiento humano.
"""

from __future__ import annotations

import copy
import random

import structlog

from streaming_bot.application.playlists.composer_config import ComposerConfig
from streaming_bot.domain.playlist import (
    Playlist,
    PlaylistKind,
    PlaylistTrack,
    PlaylistVisibility,
)
from streaming_bot.domain.ports.playlist_repo import ICamouflagePool
from streaming_bot.domain.song import Song
from streaming_bot.domain.value_objects import Country


class DefaultPlaylistComposer:
    """Compositor de playlists con mezcla estratégica target+camuflaje."""

    def __init__(
        self,
        camouflage: ICamouflagePool,
        config: ComposerConfig,
        logger: structlog.BoundLogger | None = None,
    ) -> None:
        self._camouflage = camouflage
        self._config = config
        self._logger = logger or structlog.get_logger()
        self._rng = random.Random(config.rng_seed)  # noqa: S311

    async def compose_personal_playlist(
        self,
        *,
        account_id: str,
        market: Country,
        target_songs: list[Song],
        target_ratio: float = 0.30,
        size: int = 30,
    ) -> Playlist:
        """Crea una playlist privada para una cuenta con mezcla balanceada."""
        # Calcular número de targets con jitter
        jitter = self._rng.uniform(
            -self._config.target_ratio_jitter,
            self._config.target_ratio_jitter,
        )
        effective_ratio = max(0.0, min(1.0, target_ratio + jitter))
        n_targets = round(size * effective_ratio)
        n_targets = max(1, min(n_targets, len(target_songs), size - 1))
        n_camouflage = size - n_targets

        # Sample targets y camuflaje
        sampled_targets = self._rng.sample(target_songs, n_targets)
        excluding_uris = {s.spotify_uri for s in target_songs}
        camouflage_tracks = await self._camouflage.random_sample(
            market=market,
            size=n_camouflage,
            excluding_uris=excluding_uris,
        )

        # Construir tracks intercalados
        tracks = self._interleave_tracks(
            targets=sampled_targets,
            camouflage=camouflage_tracks,
        )

        # Crear playlist
        playlist = Playlist.new(
            name=f"Mix · {account_id[:6]}",
            kind=PlaylistKind.PERSONAL_PRIVATE,
            visibility=PlaylistVisibility.PRIVATE,
            owner_account_id=account_id,
            territory=market,
            genre=None,
        )
        playlist.tracks = tracks

        self._logger.debug(
            "composed_personal_playlist",
            account_id=account_id,
            market=market.value,
            size=size,
            n_targets=n_targets,
            n_camouflage=n_camouflage,
        )

        return playlist

    async def compose_project_playlist(
        self,
        *,
        market: Country,
        genre: str,
        target_songs: list[Song],
        target_ratio: float = 0.20,
        size: int = 50,
    ) -> Playlist:
        """Crea una playlist pública de proyecto (con curator account)."""
        # Calcular número de targets con jitter
        jitter = self._rng.uniform(
            -self._config.target_ratio_jitter,
            self._config.target_ratio_jitter,
        )
        effective_ratio = max(0.0, min(1.0, target_ratio + jitter))
        n_targets = round(size * effective_ratio)
        n_targets = max(1, min(n_targets, len(target_songs), size - 1))
        n_camouflage = size - n_targets

        # Sample targets y camuflaje
        sampled_targets = self._rng.sample(target_songs, n_targets)
        excluding_uris = {s.spotify_uri for s in target_songs}
        camouflage_tracks = await self._camouflage.fetch_top_by_genre(
            genre=genre,
            market=market,
            limit=n_camouflage,
        )

        # Si no hay suficiente camuflaje del género, completar con random
        if len(camouflage_tracks) < n_camouflage:
            additional = await self._camouflage.random_sample(
                market=market,
                size=n_camouflage - len(camouflage_tracks),
                excluding_uris=excluding_uris | {t.track_uri for t in camouflage_tracks},
            )
            camouflage_tracks.extend(additional)

        # Construir tracks intercalados
        tracks = self._interleave_tracks(
            targets=sampled_targets,
            camouflage=camouflage_tracks,
        )

        # Crear playlist
        playlist = Playlist.new(
            name=f"{genre.title()} · {market.value}",
            kind=PlaylistKind.PROJECT_PUBLIC,
            visibility=PlaylistVisibility.PUBLIC,
            owner_account_id=None,
            territory=market,
            genre=genre,
        )
        playlist.tracks = tracks

        self._logger.debug(
            "composed_project_playlist",
            market=market.value,
            genre=genre,
            size=size,
            n_targets=n_targets,
            n_camouflage=n_camouflage,
        )

        return playlist

    async def reorder_for_session(
        self,
        playlist: Playlist,
        *,
        session_target_uris: set[str],
    ) -> Playlist:
        """Reordena la playlist para esta sesión: targets bien repartidos."""
        # Clonar playlist
        reordered = copy.deepcopy(playlist)

        # Separar targets de sesión vs resto
        session_targets = [
            t for t in reordered.tracks if t.is_target and t.track_uri in session_target_uris
        ]
        other_tracks = [
            t for t in reordered.tracks if not (t.is_target and t.track_uri in session_target_uris)
        ]

        if not session_targets:
            self._logger.warning(
                "reorder_for_session_no_targets",
                playlist_id=playlist.id,
                session_target_uris=session_target_uris,
            )
            return reordered

        # Distribuir targets uniformemente
        n_session_targets = len(session_targets)
        total_size = len(reordered.tracks)
        interval = total_size // n_session_targets if n_session_targets > 0 else total_size

        # Crear nueva lista con targets distribuidos
        new_tracks: list[PlaylistTrack] = []
        other_idx = 0
        for i, target in enumerate(session_targets):
            # Posición target = i * interval
            target_position = i * interval

            # Rellenar con otros tracks hasta la posición del target
            while len(new_tracks) < target_position and other_idx < len(other_tracks):
                new_tracks.append(other_tracks[other_idx])
                other_idx += 1

            # Insertar target
            new_tracks.append(target)

        # Agregar tracks restantes
        while other_idx < len(other_tracks):
            new_tracks.append(other_tracks[other_idx])
            other_idx += 1

        # Reasignar posiciones
        for idx, track in enumerate(new_tracks):
            new_tracks[idx] = PlaylistTrack(
                track_uri=track.track_uri,
                position=idx,
                is_target=track.is_target,
                duration_ms=track.duration_ms,
                artist_uri=track.artist_uri,
                title=track.title,
            )

        reordered.tracks = new_tracks

        self._logger.debug(
            "reordered_for_session",
            playlist_id=playlist.id,
            n_session_targets=n_session_targets,
            interval=interval,
        )

        return reordered

    def _interleave_tracks(
        self,
        *,
        targets: list[Song],
        camouflage: list[PlaylistTrack],
    ) -> list[PlaylistTrack]:
        """Intercala targets y camuflaje con anti-contiguidad."""
        # Convertir targets a PlaylistTrack
        target_tracks = [
            PlaylistTrack(
                track_uri=s.spotify_uri,
                position=0,
                is_target=True,
                duration_ms=s.metadata.duration_seconds * 1000,
                artist_uri=s.artist_uri,
                title=s.title,
            )
            for s in targets
        ]

        # Shuffle ambas listas
        self._rng.shuffle(target_tracks)
        self._rng.shuffle(camouflage)

        # Estrategia: intercalar con al menos min_camouflage_between_targets
        result: list[PlaylistTrack] = []
        target_idx = 0
        camouflage_idx = 0
        min_spacing = self._config.min_camouflage_between_targets

        # Si primer track debe ser camuflaje, empezar con uno
        if self._config.avoid_first_track_target and camouflage:
            result.append(camouflage[camouflage_idx])
            camouflage_idx += 1

        while target_idx < len(target_tracks) or camouflage_idx < len(camouflage):
            # Agregar un target si quedan
            if target_idx < len(target_tracks):
                result.append(target_tracks[target_idx])
                target_idx += 1

                # Agregar spacing de camuflaje
                for _ in range(min_spacing):
                    if camouflage_idx < len(camouflage):
                        result.append(camouflage[camouflage_idx])
                        camouflage_idx += 1
            elif camouflage_idx < len(camouflage):
                # Solo quedan camuflaje, agregar todos
                result.append(camouflage[camouflage_idx])
                camouflage_idx += 1

        # Reasignar posiciones
        for idx, track in enumerate(result):
            result[idx] = PlaylistTrack(
                track_uri=track.track_uri,
                position=idx,
                is_target=track.is_target,
                duration_ms=track.duration_ms,
                artist_uri=track.artist_uri,
                title=track.title,
            )

        return result
