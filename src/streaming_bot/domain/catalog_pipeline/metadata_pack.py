"""``MetadataPack``: metadata enriquecida lista para un distribuidor.

Combina los outputs del LLM (titulo, tags, descripcion) con la portada
generada por la IA de imagenes. El use case del pipeline lo construye y se
lo entrega al dispatcher de distribuidores.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MetadataPack:
    """Metadata generada por LLM mas portada generada por imagen IA.

    Atributos:
        title: titulo creativo final.
        artist_alias: alias publico del artista para esta pista.
        genre: macro-genero (ej. ``ambient``, ``lo-fi``).
        subgenre: sub-genero (ej. ``deep-sleep``, ``study-beats``).
        tags: tags SEO para tiendas (Spotify, Apple, Amazon Music).
        description: copy SEO/marketing.
        cover_art_path: ruta al PNG/JPG 3000x3000 de la portada.
    """

    title: str
    artist_alias: str
    genre: str
    subgenre: str
    tags: tuple[str, ...]
    description: str
    cover_art_path: Path

    def __post_init__(self) -> None:
        if not self.title:
            raise ValueError("title no puede estar vacio")
        if not self.artist_alias:
            raise ValueError("artist_alias no puede estar vacio")
        if not self.genre:
            raise ValueError("genre no puede estar vacio")
        if not self.tags:
            raise ValueError("tags no puede estar vacio")
