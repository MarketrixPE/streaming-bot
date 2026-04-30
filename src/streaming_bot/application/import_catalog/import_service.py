"""Caso de uso: importar catalogos de distribuidor al sistema.

Orquesta:
- Auto-deteccion del parser (``DistributorParserDetector``).
- Aggregation y normalizacion (``IDistributorParser``).
- Upsert de ``Artist`` y ``Label`` con cache (``ArtistUpserter``,
  ``LabelUpserter``).
- Clasificacion de tier y deteccion de spike/flagged (``TierClassifier``).
- Idempotencia: si la cancion ya existe (lookup por ISRC/URI), se actualiza
  in-place; nunca se crea duplicada.
- Modo ``dry_run``: produce el ``ImportSummary`` sin escribir nada.

Dependencias inyectadas (DIP): el servicio depende solo de Protocols del
dominio, no de implementaciones concretas.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from streaming_bot.application.import_catalog.parsers import (
    DistributorParserDetector,
    IDistributorParser,
    ParsedCatalogRow,
)
from streaming_bot.application.import_catalog.tier_classifier import (
    TierClassifier,
    load_flagged_oct2025,
)
from streaming_bot.application.import_catalog.upsert import (
    ArtistUpserter,
    LabelUpserter,
)
from streaming_bot.domain.artist import Artist
from streaming_bot.domain.label import DistributorType, Label
from streaming_bot.domain.ports.artist_repo import IArtistRepository
from streaming_bot.domain.ports.label_repo import ILabelRepository
from streaming_bot.domain.ports.song_repo import ISongRepository
from streaming_bot.domain.song import (
    Distributor,
    Song,
    SongMetadata,
    SongRole,
    SongTier,
)

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger


@dataclass(slots=True)
class ImportSummary:
    """Resumen estadistico devuelto al caller del import.

    Es un value object: serializable, comparable por valor.
    """

    rows_seen: int = 0
    songs_created: int = 0
    songs_updated: int = 0
    songs_skipped: int = 0
    artists_created: int = 0
    labels_created: int = 0
    flagged_count: int = 0
    by_tier: dict[SongTier, int] = field(default_factory=dict)
    dry_run: bool = False
    errors: list[str] = field(default_factory=list)

    def increment_tier(self, tier: SongTier) -> None:
        self.by_tier[tier] = self.by_tier.get(tier, 0) + 1

    def add_error(self, message: str) -> None:
        self.errors.append(message)


# Mapping desde ``DistributorType`` (Label) a ``Distributor`` (Song). Existen
# dos enums porque modelan responsabilidades distintas; el mapping aqui es la
# unica frontera donde se cruzan.
_DISTRIBUTOR_MAP: dict[DistributorType, Distributor] = {
    DistributorType.DISTROKID: Distributor.DISTROKID,
    DistributorType.ONERPM: Distributor.ONERPM,
    DistributorType.UNITED_MASTERS: Distributor.UNITED_MASTERS,
    DistributorType.AICOM: Distributor.OTHER,
    DistributorType.SPOTIFY_FOR_ARTISTS: Distributor.OTHER,
    DistributorType.AMUSE: Distributor.OTHER,
    DistributorType.OTHER: Distributor.OTHER,
}


class ImportCatalogService:
    """Orquestador del flujo de import.

    No conoce de SQL ni de pandas: depende solo de protocols.
    """

    def __init__(
        self,
        *,
        artists: IArtistRepository,
        labels: ILabelRepository,
        songs: ISongRepository,
        classifier: TierClassifier,
        logger: BoundLogger,
        flagged_oct2025_path: Path | None = None,
    ) -> None:
        self._artists = artists
        self._labels = labels
        self._songs = songs
        self._classifier = classifier
        self._logger = logger.bind(component="import_catalog")
        self._flagged_path = flagged_oct2025_path
        self._flagged_cache: set[str] | None = None

    async def import_file(
        self,
        path: Path,
        *,
        artist_id: str | None = None,
        label_id: str | None = None,
        distributor: DistributorType | None = None,
        dry_run: bool = False,
        parser: IDistributorParser | None = None,
    ) -> ImportSummary:
        """Importa un archivo y devuelve el resumen.

        Args:
            path: Ruta al archivo (xlsx/csv).
            artist_id: Si se especifica, fuerza este artist_id como primario.
            label_id: Si se especifica, fuerza este label_id.
            distributor: Distribuidor explicito; si es ``None``, se infiere
                del parser detectado.
            dry_run: Si ``True``, no escribe en repos.
            parser: Override del parser auto-detectado (util para tests).
        """
        summary = ImportSummary(dry_run=dry_run)
        try:
            chosen = parser or DistributorParserDetector.detect(path)
        except ValueError as exc:
            summary.add_error(str(exc))
            self._logger.error("parser_detection_failed", path=str(path), error=str(exc))
            return summary

        effective_distributor = distributor or chosen.distributor
        flagged_set = self._load_flagged_set()

        artist_upserter = ArtistUpserter(self._artists, dry_run=dry_run)
        label_upserter = LabelUpserter(self._labels, dry_run=dry_run)

        explicit_artist = await self._resolve_explicit_artist(artist_id)
        explicit_label = await self._resolve_explicit_label(label_id)

        for row in chosen.parse(path):
            summary.rows_seen += 1
            try:
                await self._process_row(
                    row=row,
                    summary=summary,
                    distributor=effective_distributor,
                    flagged_set=flagged_set,
                    artist_upserter=artist_upserter,
                    label_upserter=label_upserter,
                    explicit_artist=explicit_artist,
                    explicit_label=explicit_label,
                    dry_run=dry_run,
                )
            except (ValueError, RuntimeError) as exc:  # pragma: no cover — defensivo
                msg = f"row_failed[{row.title}]: {exc}"
                summary.add_error(msg)
                summary.songs_skipped += 1
                self._logger.warning("import_row_failed", title=row.title, error=str(exc))

        summary.artists_created = artist_upserter.stats.created
        summary.labels_created = label_upserter.stats.created
        self._logger.info(
            "import_complete",
            path=str(path),
            rows_seen=summary.rows_seen,
            songs_created=summary.songs_created,
            songs_updated=summary.songs_updated,
            artists_created=summary.artists_created,
            labels_created=summary.labels_created,
            flagged_count=summary.flagged_count,
            dry_run=dry_run,
        )
        return summary

    # ── Logica por row ───────────────────────────────────────────────────────
    async def _process_row(
        self,
        *,
        row: ParsedCatalogRow,
        summary: ImportSummary,
        distributor: DistributorType,
        flagged_set: set[str],
        artist_upserter: ArtistUpserter,
        label_upserter: LabelUpserter,
        explicit_artist: Artist | None,
        explicit_label: Label | None,
        dry_run: bool,
    ) -> None:
        # Resolver Label
        label: Label | None
        if explicit_label is not None:
            label = explicit_label
        elif row.label_name:
            label = await label_upserter.upsert(
                name=row.label_name,
                distributor=distributor,
            )
        else:
            label = None

        # Resolver Artist primario
        if explicit_artist is not None:
            artist = explicit_artist
        else:
            artist = await artist_upserter.upsert(
                name=row.artist_name,
                label_id=label.id if label else None,
            )

        # Resolver Artists featured (mismo upserter -> cache compartida)
        featured_ids: list[str] = []
        for feat_name in row.featured_artist_names:
            feat = await artist_upserter.upsert(name=feat_name)
            featured_ids.append(feat.id)

        # Tier + flag
        tier = self._classifier.classify(row)
        flagged = self._is_row_flagged(row, flagged_set)
        if flagged:
            tier = SongTier.FLAGGED
            summary.flagged_count += 1
        summary.increment_tier(tier)

        # Resolver Song existente (idempotencia)
        spotify_uri = row.synthesize_spotify_uri()
        existing = await self._find_existing_song(spotify_uri=spotify_uri, isrc=row.isrc)

        song = self._build_song(
            row=row,
            spotify_uri=spotify_uri,
            tier=tier,
            flagged=flagged,
            artist=artist,
            featured_ids=tuple(featured_ids),
            label=label,
        )

        if existing is not None:
            self._merge_into(existing, song)
            if not dry_run:
                await self._songs.update(existing)
            summary.songs_updated += 1
        else:
            if not dry_run:
                await self._songs.add(song)
            summary.songs_created += 1

    async def _find_existing_song(
        self,
        *,
        spotify_uri: str,
        isrc: str | None,
    ) -> Song | None:
        existing = await self._songs.get_by_uri(spotify_uri)
        if existing is not None:
            return existing
        if isrc:
            return await self._songs.get_by_isrc(isrc)
        return None

    def _build_song(
        self,
        *,
        row: ParsedCatalogRow,
        spotify_uri: str,
        tier: SongTier,
        flagged: bool,
        artist: Artist,
        featured_ids: tuple[str, ...],
        label: Label | None,
    ) -> Song:
        metadata = SongMetadata(
            duration_seconds=0,
            release_date=row.release_date,
            isrc=row.isrc,
            label=label.name if label else row.label_name,
        )
        artist_uri = artist.spotify_uri or f"spotify:artist:{artist.id}"
        return Song(
            spotify_uri=spotify_uri,
            title=row.title,
            artist_name=artist.name,
            artist_uri=artist_uri,
            role=SongRole.TARGET,
            metadata=metadata,
            primary_artist_id=artist.id,
            featured_artist_ids=featured_ids,
            label_id=label.id if label else None,
            distributor=_DISTRIBUTOR_MAP.get(
                row.distributor or DistributorType.OTHER,
                Distributor.OTHER,
            ),
            baseline_streams_per_day=row.avg_streams_per_month / 30.0,
            target_streams_per_day=int(row.avg_streams_per_month / 30.0 * 1.5),
            tier=tier,
            spike_oct2025_flag=flagged,
            flag_notes=("flagged_oct2025" if flagged else ""),
        )

    @staticmethod
    def _merge_into(existing: Song, fresh: Song) -> None:
        """Mutates ``existing`` con los campos refrescables de ``fresh``."""
        existing.title = fresh.title
        existing.artist_name = fresh.artist_name
        existing.artist_uri = fresh.artist_uri
        existing.primary_artist_id = fresh.primary_artist_id
        existing.featured_artist_ids = fresh.featured_artist_ids
        existing.label_id = fresh.label_id
        existing.distributor = fresh.distributor
        existing.baseline_streams_per_day = fresh.baseline_streams_per_day
        existing.target_streams_per_day = fresh.target_streams_per_day
        existing.tier = fresh.tier
        existing.spike_oct2025_flag = fresh.spike_oct2025_flag
        existing.flag_notes = fresh.flag_notes
        existing.metadata = fresh.metadata

    def _is_row_flagged(
        self,
        row: ParsedCatalogRow,
        flagged_set: set[str],
    ) -> bool:
        candidates = [row.synthesize_spotify_uri()]
        if row.isrc:
            candidates.append(row.isrc)
        return any(TierClassifier.is_flagged_oct2025(c, flagged_set) for c in candidates)

    def _load_flagged_set(self) -> set[str]:
        if self._flagged_cache is not None:
            return self._flagged_cache
        self._flagged_cache = (
            load_flagged_oct2025(self._flagged_path) if self._flagged_path else set()
        )
        return self._flagged_cache

    async def _resolve_explicit_artist(self, artist_id: str | None) -> Artist | None:
        if not artist_id:
            return None
        artist = await self._artists.get(artist_id)
        if artist is None:
            self._logger.warning("explicit_artist_not_found", artist_id=artist_id)
        return artist

    async def _resolve_explicit_label(self, label_id: str | None) -> Label | None:
        if not label_id:
            return None
        label = await self._labels.get(label_id)
        if label is None:
            self._logger.warning("explicit_label_not_found", label_id=label_id)
        return label


def summarize_by_tier(songs: list[Song]) -> Counter[SongTier]:
    """Cuenta canciones por tier (helper para CLI ``catalog stats``)."""
    return Counter(song.tier for song in songs)


__all__ = [
    "ImportCatalogService",
    "ImportSummary",
    "summarize_by_tier",
]
