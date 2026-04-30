"""Repositorios temporales basados en JSON para Artist/Label/Song.

Estos repositorios cubren la transicion entre la entrega de la feature de
import de catalogos y el cableado completo a Postgres (responsabilidad del
siguiente agente de container-wiring).

Diseno:
- Persistencia: un archivo JSON por entidad bajo ``base_dir``.
- Concurrencia: un ``asyncio.Lock`` por archivo (no thread-safe entre
  procesos; aceptable porque el CLI es single-process).
- Compatibilidad: implementan ``IArtistRepository``, ``ILabelRepository`` e
  ``ISongRepository`` con la misma semantica que sus contrapartes Postgres.

Cuando Postgres este cableado, el ``Container`` reemplaza estos repos por
los de SQLAlchemy sin que la capa de aplicacion se entere.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, ClassVar

from streaming_bot.domain.artist import Artist, ArtistStatus
from streaming_bot.domain.label import DistributorType, Label, LabelHealth
from streaming_bot.domain.song import (
    Distributor,
    Song,
    SongMetadata,
    SongRole,
    SongTier,
)
from streaming_bot.domain.value_objects import Country


class _JsonStore:
    """Helper compartido para read/write atomicos de archivos JSON."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def read(self) -> list[dict[str, Any]]:
        async with self._lock:
            return self._read_unlocked()

    async def write_all(self, items: list[dict[str, Any]]) -> None:
        async with self._lock:
            self._write_unlocked(items)

    async def upsert(self, item: dict[str, Any], *, key: str = "id") -> None:
        async with self._lock:
            items = self._read_unlocked()
            existing_idx = next(
                (i for i, it in enumerate(items) if it.get(key) == item.get(key)),
                None,
            )
            if existing_idx is None:
                items.append(item)
            else:
                items[existing_idx] = item
            self._write_unlocked(items)

    async def delete_by(self, *, key: str, value: str) -> bool:
        async with self._lock:
            items = self._read_unlocked()
            new_items = [it for it in items if it.get(key) != value]
            if len(new_items) == len(items):
                return False
            self._write_unlocked(new_items)
            return True

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def _write_unlocked(self, items: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = json.dumps(items, ensure_ascii=False, indent=2, default=_json_default)
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self._path)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, tuple | list):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    return str(value)


# ── Artist ───────────────────────────────────────────────────────────────────


class JsonArtistRepository:
    """Implementacion JSON de ``IArtistRepository``."""

    FILE_NAME: ClassVar[str] = "artists.json"

    def __init__(self, base_dir: Path) -> None:
        self._store = _JsonStore(base_dir / self.FILE_NAME)

    async def save(self, artist: Artist) -> None:
        await self._store.upsert(_artist_to_dict(artist))

    async def get(self, artist_id: str) -> Artist | None:
        for item in await self._store.read():
            if item.get("id") == artist_id:
                return _artist_from_dict(item)
        return None

    async def get_by_spotify_uri(self, spotify_uri: str) -> Artist | None:
        for item in await self._store.read():
            if item.get("spotify_uri") == spotify_uri:
                return _artist_from_dict(item)
        return None

    async def get_by_name(self, name: str) -> Artist | None:
        target = name.strip().casefold()
        for item in await self._store.read():
            stored = str(item.get("name", "")).strip().casefold()
            if stored == target:
                return _artist_from_dict(item)
        return None

    async def list_active(self) -> list[Artist]:
        return await self.list_by_status(ArtistStatus.ACTIVE)

    async def list_by_status(self, status: ArtistStatus) -> list[Artist]:
        return [
            _artist_from_dict(it)
            for it in await self._store.read()
            if it.get("status") == status.value
        ]

    async def list_all(self) -> list[Artist]:
        return [_artist_from_dict(it) for it in await self._store.read()]

    async def delete(self, artist_id: str) -> None:
        await self._store.delete_by(key="id", value=artist_id)


def _artist_to_dict(artist: Artist) -> dict[str, Any]:
    return {
        "id": artist.id,
        "name": artist.name,
        "spotify_uri": artist.spotify_uri,
        "aliases": list(artist.aliases),
        "primary_country": artist.primary_country.value if artist.primary_country else None,
        "primary_genres": list(artist.primary_genres),
        "label_id": artist.label_id,
        "status": artist.status.value,
        "has_spike_history": artist.has_spike_history,
        "notes": artist.notes,
        "created_at": artist.created_at.isoformat(),
        "updated_at": artist.updated_at.isoformat(),
    }


def _artist_from_dict(data: dict[str, Any]) -> Artist:
    country_raw = data.get("primary_country")
    return Artist(
        id=str(data["id"]),
        name=str(data.get("name", "")),
        spotify_uri=data.get("spotify_uri"),
        aliases=tuple(data.get("aliases", []) or []),
        primary_country=Country(country_raw) if country_raw else None,
        primary_genres=tuple(data.get("primary_genres", []) or []),
        label_id=data.get("label_id"),
        status=ArtistStatus(data.get("status", ArtistStatus.ACTIVE.value)),
        has_spike_history=bool(data.get("has_spike_history", False)),
        notes=str(data.get("notes", "")),
        created_at=_parse_datetime(data.get("created_at")),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


# ── Label ────────────────────────────────────────────────────────────────────


class JsonLabelRepository:
    """Implementacion JSON de ``ILabelRepository``."""

    FILE_NAME: ClassVar[str] = "labels.json"

    def __init__(self, base_dir: Path) -> None:
        self._store = _JsonStore(base_dir / self.FILE_NAME)

    async def save(self, label: Label) -> None:
        await self._store.upsert(_label_to_dict(label))

    async def get(self, label_id: str) -> Label | None:
        for item in await self._store.read():
            if item.get("id") == label_id:
                return _label_from_dict(item)
        return None

    async def get_by_name(self, name: str) -> Label | None:
        target = name.strip().casefold()
        for item in await self._store.read():
            if str(item.get("name", "")).strip().casefold() == target:
                return _label_from_dict(item)
        return None

    async def list_by_distributor(self, distributor: DistributorType) -> list[Label]:
        return [
            _label_from_dict(it)
            for it in await self._store.read()
            if it.get("distributor") == distributor.value
        ]

    async def list_by_health(self, health: LabelHealth) -> list[Label]:
        return [
            _label_from_dict(it)
            for it in await self._store.read()
            if it.get("health") == health.value
        ]

    async def list_all(self) -> list[Label]:
        return [_label_from_dict(it) for it in await self._store.read()]

    async def delete(self, label_id: str) -> None:
        await self._store.delete_by(key="id", value=label_id)


def _label_to_dict(label: Label) -> dict[str, Any]:
    return {
        "id": label.id,
        "name": label.name,
        "distributor": label.distributor.value,
        "distributor_account_id": label.distributor_account_id,
        "owner_email": label.owner_email,
        "health": label.health.value,
        "last_health_check": (
            label.last_health_check.isoformat() if label.last_health_check else None
        ),
        "notes": label.notes,
        "created_at": label.created_at.isoformat(),
        "updated_at": label.updated_at.isoformat(),
    }


def _label_from_dict(data: dict[str, Any]) -> Label:
    last_check_raw = data.get("last_health_check")
    return Label(
        id=str(data["id"]),
        name=str(data.get("name", "")),
        distributor=DistributorType(data.get("distributor", DistributorType.OTHER.value)),
        distributor_account_id=data.get("distributor_account_id"),
        owner_email=data.get("owner_email"),
        health=LabelHealth(data.get("health", LabelHealth.HEALTHY.value)),
        last_health_check=_parse_datetime(last_check_raw) if last_check_raw else None,
        notes=str(data.get("notes", "")),
        created_at=_parse_datetime(data.get("created_at")),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


# ── Song ─────────────────────────────────────────────────────────────────────


class JsonSongRepository:
    """Implementacion JSON parcial de ``ISongRepository``.

    Cubre los metodos que necesita el ``ImportCatalogService`` y el CLI
    (catalog list/stats). Los metodos para piloto reusan el mismo storage.
    """

    FILE_NAME: ClassVar[str] = "songs.json"

    def __init__(self, base_dir: Path) -> None:
        self._store = _JsonStore(base_dir / self.FILE_NAME)

    async def get(self, song_id: str) -> Song | None:
        for item in await self._store.read():
            if item.get("spotify_uri") == song_id:
                return _song_from_dict(item)
        return None

    async def get_by_uri(self, uri: str) -> Song | None:
        for item in await self._store.read():
            if item.get("spotify_uri") == uri:
                return _song_from_dict(item)
        return None

    async def get_by_isrc(self, isrc: str) -> Song | None:
        for item in await self._store.read():
            metadata = item.get("metadata") or {}
            if metadata.get("isrc") == isrc:
                return _song_from_dict(item)
        return None

    async def add(self, song: Song) -> None:
        await self._store.upsert(_song_to_dict(song), key="spotify_uri")

    async def update(self, song: Song) -> None:
        await self._store.upsert(_song_to_dict(song), key="spotify_uri")

    async def list_by_role(self, role: SongRole) -> list[Song]:
        return [
            _song_from_dict(it) for it in await self._store.read() if it.get("role") == role.value
        ]

    async def list_targets_by_market(self, market: Country) -> list[Song]:
        out: list[Song] = []
        for it in await self._store.read():
            if it.get("role") != SongRole.TARGET.value:
                continue
            top = it.get("top_country_distribution", {}) or {}
            if market.value in top:
                out.append(_song_from_dict(it))
        return out

    async def list_pilot_eligible(self, *, max_songs: int = 60) -> list[Song]:
        eligible: list[Song] = []
        for it in await self._store.read():
            song = _song_from_dict(it)
            if song.is_pilot_eligible:
                eligible.append(song)
        return eligible[:max_songs]

    async def count_active_targets(self) -> int:
        count = 0
        for it in await self._store.read():
            if it.get("role") == SongRole.TARGET.value and bool(it.get("is_active", True)):
                count += 1
        return count

    async def list_all(self) -> list[Song]:
        return [_song_from_dict(it) for it in await self._store.read()]


def _song_to_dict(song: Song) -> dict[str, Any]:
    metadata = song.metadata
    return {
        "spotify_uri": song.spotify_uri,
        "title": song.title,
        "artist_name": song.artist_name,
        "artist_uri": song.artist_uri,
        "role": song.role.value,
        "metadata": {
            "duration_seconds": metadata.duration_seconds,
            "explicit": metadata.explicit,
            "release_date": metadata.release_date.isoformat() if metadata.release_date else None,
            "isrc": metadata.isrc,
            "album_uri": metadata.album_uri,
            "label": metadata.label,
            "genres": list(metadata.genres),
            "primary_market": metadata.primary_market.value if metadata.primary_market else None,
        },
        "primary_artist_id": song.primary_artist_id,
        "featured_artist_ids": list(song.featured_artist_ids),
        "label_id": song.label_id,
        "distributor": song.distributor.value if song.distributor else None,
        "baseline_streams_per_day": song.baseline_streams_per_day,
        "target_streams_per_day": song.target_streams_per_day,
        "current_streams_today": song.current_streams_today,
        "is_active": song.is_active,
        "tier": song.tier.value,
        "spike_oct2025_flag": song.spike_oct2025_flag,
        "flag_notes": song.flag_notes,
        "top_country_distribution": {
            (k.value if hasattr(k, "value") else str(k)): v
            for k, v in song.top_country_distribution.items()
        },
    }


def _song_from_dict(data: dict[str, Any]) -> Song:
    md_raw = data.get("metadata") or {}
    md_release = md_raw.get("release_date")
    md_market = md_raw.get("primary_market")
    metadata = SongMetadata(
        duration_seconds=int(md_raw.get("duration_seconds", 0)),
        explicit=bool(md_raw.get("explicit", False)),
        release_date=date.fromisoformat(md_release) if md_release else None,
        isrc=md_raw.get("isrc"),
        album_uri=md_raw.get("album_uri"),
        label=md_raw.get("label"),
        genres=tuple(md_raw.get("genres", []) or []),
        primary_market=Country(md_market) if md_market else None,
    )
    distributor_raw = data.get("distributor")
    distribution_raw = data.get("top_country_distribution", {}) or {}
    distribution = {
        Country(k): float(v) for k, v in distribution_raw.items() if k in Country.__members__
    }
    return Song(
        spotify_uri=str(data["spotify_uri"]),
        title=str(data.get("title", "")),
        artist_name=str(data.get("artist_name", "")),
        artist_uri=str(data.get("artist_uri", "")),
        role=SongRole(data.get("role", SongRole.TARGET.value)),
        metadata=metadata,
        primary_artist_id=data.get("primary_artist_id"),
        featured_artist_ids=tuple(data.get("featured_artist_ids", []) or []),
        label_id=data.get("label_id"),
        distributor=Distributor(distributor_raw) if distributor_raw else None,
        baseline_streams_per_day=float(data.get("baseline_streams_per_day", 0.0)),
        target_streams_per_day=int(data.get("target_streams_per_day", 0)),
        current_streams_today=int(data.get("current_streams_today", 0)),
        is_active=bool(data.get("is_active", True)),
        tier=SongTier(data.get("tier", SongTier.MID.value)),
        spike_oct2025_flag=bool(data.get("spike_oct2025_flag", False)),
        flag_notes=str(data.get("flag_notes", "")),
        top_country_distribution=distribution,
    )


def _parse_datetime(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return datetime.now(UTC)
    return datetime.now(UTC)


__all__ = [
    "JsonArtistRepository",
    "JsonLabelRepository",
    "JsonSongRepository",
]
