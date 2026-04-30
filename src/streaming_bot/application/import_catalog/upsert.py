"""Upserters para Artist y Label con cache para evitar N+1.

Estos helpers encapsulan la logica de "find-or-create" que se ejecuta para
cada row del import. Sin cache, un import de 5k filas hace 5k consultas SQL
para resolver el mismo artista. La cache lo reduce a 1 query por nombre/URI.

El cache vive en memoria por instancia: el ImportCatalogService crea uno
por archivo importado.
"""

from __future__ import annotations

from dataclasses import dataclass

from streaming_bot.domain.artist import Artist
from streaming_bot.domain.label import DistributorType, Label
from streaming_bot.domain.ports.artist_repo import IArtistRepository
from streaming_bot.domain.ports.label_repo import ILabelRepository


@dataclass(slots=True)
class UpsertStats:
    """Contador de operaciones realizadas para reportar al servicio."""

    created: int = 0
    found: int = 0


class ArtistUpserter:
    """Resuelve o crea ``Artist`` evitando consultas redundantes.

    Estrategia de cache:
    1. Cache por ``spotify_uri`` cuando esta disponible.
    2. Cache por ``name`` lowercase como fallback estable.

    El cache es escrito tras ``save`` para que el siguiente lookup en el mismo
    import no toque la DB.
    """

    def __init__(self, repo: IArtistRepository, *, dry_run: bool = False) -> None:
        self._repo = repo
        self._dry_run = dry_run
        self._by_uri: dict[str, Artist] = {}
        self._by_name: dict[str, Artist] = {}
        self.stats = UpsertStats()

    async def upsert(
        self,
        *,
        name: str,
        spotify_uri: str | None = None,
        label_id: str | None = None,
    ) -> Artist:
        """Devuelve un ``Artist`` existente o lo crea y guarda.

        El upsert es idempotente: importar dos veces el mismo archivo
        genera 0 nuevos ``Artist``.
        """
        cleaned_name = name.strip()
        name_key = cleaned_name.casefold()
        uri_key = spotify_uri.strip() if spotify_uri else None

        if uri_key and uri_key in self._by_uri:
            self.stats.found += 1
            return self._by_uri[uri_key]
        if name_key in self._by_name:
            self.stats.found += 1
            return self._by_name[name_key]

        # Lookup en repo: primero por URI, luego por nombre.
        found: Artist | None = None
        if uri_key:
            found = await self._repo.get_by_spotify_uri(uri_key)
        if found is None:
            found = await self._repo.get_by_name(cleaned_name)

        artist: Artist
        if found is None:
            artist = Artist.new(
                name=cleaned_name,
                spotify_uri=uri_key,
                label_id=label_id,
            )
            if not self._dry_run:
                await self._repo.save(artist)
            self.stats.created += 1
        else:
            artist = found
            mutated = False
            if label_id and not artist.label_id:
                artist.label_id = label_id
                mutated = True
            if uri_key and not artist.spotify_uri:
                artist.spotify_uri = uri_key
                mutated = True
            if mutated and not self._dry_run:
                await self._repo.save(artist)
            self.stats.found += 1

        # Poblar cache
        if artist.spotify_uri:
            self._by_uri[artist.spotify_uri] = artist
        self._by_name[name_key] = artist
        return artist


class LabelUpserter:
    """Resuelve o crea ``Label`` por nombre + distribuidor.

    Asume que dentro de un mismo distribuidor el nombre del label es unico
    (es la realidad operativa de aiCom/DistroKid/OneRPM).
    """

    def __init__(self, repo: ILabelRepository, *, dry_run: bool = False) -> None:
        self._repo = repo
        self._dry_run = dry_run
        self._by_name: dict[tuple[str, DistributorType], Label] = {}
        self.stats = UpsertStats()

    async def upsert(
        self,
        *,
        name: str,
        distributor: DistributorType,
    ) -> Label:
        cleaned = name.strip()
        cache_key = (cleaned.casefold(), distributor)
        if cache_key in self._by_name:
            self.stats.found += 1
            return self._by_name[cache_key]

        label = await self._repo.get_by_name(cleaned)
        if label is None:
            label = Label.new(name=cleaned, distributor=distributor)
            if not self._dry_run:
                await self._repo.save(label)
            self.stats.created += 1
        else:
            self.stats.found += 1

        self._by_name[cache_key] = label
        return label


__all__ = ["ArtistUpserter", "LabelUpserter", "UpsertStats"]
