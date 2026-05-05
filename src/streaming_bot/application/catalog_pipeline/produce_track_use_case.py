"""Caso de uso: producir UNA pista AI completa.

Orquesta los puertos en este orden:

1. ``IAIMusicGenerator.generate(brief)``       -> RawAudio crudo.
2. ``IAudioMastering.master(raw, profile)``    -> RawAudio masterizado.
3. ``ICoverArtGenerator.generate(brief)``      -> ruta de portada.
4. ``IMetadataGenerator.enrich(brief, raw, ..)`` -> MetadataPack.
5. ``ISongRepository.add(song)``               -> persistencia.

Devuelve ``ProducedTrack`` con todos los artefactos para auditoria y para
que el dispatcher de distribuidores lo recoja despues.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from streaming_bot.domain.song import Song, SongMetadata, SongRole, SongTier

if TYPE_CHECKING:
    from collections.abc import Callable

    from structlog.stdlib import BoundLogger

    from streaming_bot.domain.catalog_pipeline.metadata_pack import MetadataPack
    from streaming_bot.domain.catalog_pipeline.raw_audio import RawAudio
    from streaming_bot.domain.catalog_pipeline.track_brief import TrackBrief
    from streaming_bot.domain.ports.ai_music_generator import IAIMusicGenerator
    from streaming_bot.domain.ports.audio_mastering import (
        IAudioMastering,
        MasteringProfile,
    )
    from streaming_bot.domain.ports.cover_art_generator import ICoverArtGenerator
    from streaming_bot.domain.ports.metadata_generator import IMetadataGenerator
    from streaming_bot.domain.ports.song_repo import ISongRepository


@dataclass(frozen=True, slots=True)
class ProducedTrack:
    """Resultado de la produccion: bundle listo para distribucion."""

    track_id: str
    song: Song
    raw: RawAudio
    metadata: MetadataPack


class ProduceTrackUseCase:
    """Orquestador del pipeline de produccion para una sola pista.

    DIP estricto: depende solo de los protocols del dominio. La concurrencia
    y el budget guard se delegan a ``BatchProducer``.
    """

    def __init__(
        self,
        *,
        music_generator: IAIMusicGenerator,
        mastering: IAudioMastering,
        cover_generator: ICoverArtGenerator,
        metadata_generator: IMetadataGenerator,
        songs: ISongRepository,
        mastering_profile: MasteringProfile,
        logger: BoundLogger,
        track_id_factory: Callable[[], str],
    ) -> None:
        self._music = music_generator
        self._mastering = mastering
        self._cover = cover_generator
        self._metadata = metadata_generator
        self._songs = songs
        self._profile = mastering_profile
        self._log = logger.bind(component="produce_track")
        self._track_id_factory = track_id_factory

    async def execute(self, brief: TrackBrief) -> ProducedTrack:
        """Ejecuta el pipeline completo para ``brief`` y devuelve el bundle."""
        track_id = self._track_id_factory()
        log = self._log.bind(track_id=track_id, niche=brief.niche, mood=brief.mood)
        log.info("pipeline.start")

        raw = await self._music.generate(brief, track_id=track_id)
        log.info(
            "pipeline.audio_generated",
            duration_ms=raw.duration_ms,
            sample_rate=raw.sample_rate,
            format=raw.format.value,
        )

        mastered = await self._mastering.master(raw, self._profile)
        log.info(
            "pipeline.mastered",
            target_lufs=self._profile.integrated_lufs,
            true_peak=self._profile.true_peak_db,
        )

        cover_path = await self._cover.generate(brief, track_id=track_id)
        log.info("pipeline.cover_generated", cover=str(cover_path))

        metadata = await self._metadata.enrich(
            brief,
            mastered,
            cover_art_path=cover_path,
        )
        log.info(
            "pipeline.metadata_generated",
            title=metadata.title,
            genre=metadata.genre,
            tags_count=len(metadata.tags),
        )

        song = self._build_song(track_id=track_id, mastered=mastered, metadata=metadata)
        await self._songs.add(song)
        log.info("pipeline.song_persisted", spotify_uri=song.spotify_uri)

        return ProducedTrack(
            track_id=track_id,
            song=song,
            raw=mastered,
            metadata=metadata,
        )

    def _build_song(
        self,
        *,
        track_id: str,
        mastered: RawAudio,
        metadata: MetadataPack,
    ) -> Song:
        """Construye ``Song`` con URIs ``catalog:`` mientras no exista ID
        oficial del DSP. El dispatcher luego refresca el ``spotify_uri`` real.
        """
        song_metadata = SongMetadata(
            duration_seconds=mastered.duration_seconds(),
            release_date=None,
            isrc=None,
            label=None,
            genres=(metadata.genre, metadata.subgenre),
        )
        artist_slug = self._slugify(metadata.artist_alias)
        return Song(
            spotify_uri=f"catalog:track:{track_id}",
            title=metadata.title,
            artist_name=metadata.artist_alias,
            artist_uri=f"catalog:artist:{artist_slug}",
            role=SongRole.TARGET,
            metadata=song_metadata,
            primary_artist_id=None,
            featured_artist_ids=(),
            label_id=None,
            distributor=None,
            baseline_streams_per_day=0.0,
            target_streams_per_day=0,
            tier=SongTier.LOW,
            spike_oct2025_flag=False,
            flag_notes="",
        )

    @staticmethod
    def _slugify(value: str) -> str:
        """Slug ASCII basico (minusculas, guiones)."""
        cleaned = "".join(c if c.isalnum() else "-" for c in value.lower())
        return "-".join(part for part in cleaned.split("-") if part) or "anon"
