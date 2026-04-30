"""Fakes en memoria de IArtistRepository, ILabelRepository, ISongRepository.

Implementaciones determministas para tests del pipeline de import.
"""

from __future__ import annotations

from collections import Counter

from streaming_bot.domain.artist import Artist, ArtistStatus
from streaming_bot.domain.label import DistributorType, Label, LabelHealth
from streaming_bot.domain.song import Song, SongRole
from streaming_bot.domain.value_objects import Country


class FakeArtistRepository:
    def __init__(self) -> None:
        self._items: dict[str, Artist] = {}
        self.calls: Counter[str] = Counter()

    async def save(self, artist: Artist) -> None:
        self.calls["save"] += 1
        self._items[artist.id] = artist

    async def get(self, artist_id: str) -> Artist | None:
        self.calls["get"] += 1
        return self._items.get(artist_id)

    async def get_by_spotify_uri(self, spotify_uri: str) -> Artist | None:
        self.calls["get_by_spotify_uri"] += 1
        for a in self._items.values():
            if a.spotify_uri == spotify_uri:
                return a
        return None

    async def get_by_name(self, name: str) -> Artist | None:
        self.calls["get_by_name"] += 1
        target = name.strip().casefold()
        for a in self._items.values():
            if a.name.strip().casefold() == target:
                return a
        return None

    async def list_active(self) -> list[Artist]:
        return await self.list_by_status(ArtistStatus.ACTIVE)

    async def list_by_status(self, status: ArtistStatus) -> list[Artist]:
        return [a for a in self._items.values() if a.status == status]

    async def list_all(self) -> list[Artist]:
        return list(self._items.values())

    async def delete(self, artist_id: str) -> None:
        self._items.pop(artist_id, None)


class FakeLabelRepository:
    def __init__(self) -> None:
        self._items: dict[str, Label] = {}
        self.calls: Counter[str] = Counter()

    async def save(self, label: Label) -> None:
        self.calls["save"] += 1
        self._items[label.id] = label

    async def get(self, label_id: str) -> Label | None:
        self.calls["get"] += 1
        return self._items.get(label_id)

    async def get_by_name(self, name: str) -> Label | None:
        self.calls["get_by_name"] += 1
        target = name.strip().casefold()
        for label in self._items.values():
            if label.name.strip().casefold() == target:
                return label
        return None

    async def list_by_distributor(self, distributor: DistributorType) -> list[Label]:
        return [label for label in self._items.values() if label.distributor == distributor]

    async def list_by_health(self, health: LabelHealth) -> list[Label]:
        return [label for label in self._items.values() if label.health == health]

    async def list_all(self) -> list[Label]:
        return list(self._items.values())

    async def delete(self, label_id: str) -> None:
        self._items.pop(label_id, None)


class FakeSongRepository:
    def __init__(self) -> None:
        self._items: dict[str, Song] = {}
        self.calls: Counter[str] = Counter()

    async def get(self, song_id: str) -> Song | None:
        return self._items.get(song_id)

    async def get_by_uri(self, uri: str) -> Song | None:
        self.calls["get_by_uri"] += 1
        return self._items.get(uri)

    async def get_by_isrc(self, isrc: str) -> Song | None:
        self.calls["get_by_isrc"] += 1
        for song in self._items.values():
            if song.metadata.isrc == isrc:
                return song
        return None

    async def add(self, song: Song) -> None:
        self.calls["add"] += 1
        self._items[song.spotify_uri] = song

    async def update(self, song: Song) -> None:
        self.calls["update"] += 1
        self._items[song.spotify_uri] = song

    async def list_by_role(self, role: SongRole) -> list[Song]:
        return [s for s in self._items.values() if s.role == role]

    async def list_targets_by_market(self, market: Country) -> list[Song]:
        return [
            s
            for s in self._items.values()
            if s.role == SongRole.TARGET and market in s.top_country_distribution
        ]

    async def list_pilot_eligible(self, *, max_songs: int = 60) -> list[Song]:
        eligible = [s for s in self._items.values() if s.is_pilot_eligible]
        return eligible[:max_songs]

    async def count_active_targets(self) -> int:
        return sum(1 for s in self._items.values() if s.is_target and s.is_active)

    async def list_all(self) -> list[Song]:
        return list(self._items.values())


__all__ = [
    "FakeArtistRepository",
    "FakeLabelRepository",
    "FakeSongRepository",
]
