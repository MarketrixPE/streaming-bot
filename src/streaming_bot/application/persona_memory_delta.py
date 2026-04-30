"""Delta incremental de cambios en la PersonaMemory durante una sesion.

El `HumanBehaviorEngine` acumula aqui los efectos secundarios (likes, saves,
follows, etc.) generados durante la sesion. Al final, el `PlaylistSessionUseCase`
solicita aplicar el delta sobre la `Persona` y persistirla via
`IPersonaRepository.update_memory()`.

Razon de este intermediario:
- Mantenemos la engine pura (no muta la persona directamente).
- Permite tests deterministas (verificar el delta sin pisar la entidad).
- Acota la zona de cambio: el use case decide cuando "commitear".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from streaming_bot.domain.persona import Persona


@dataclass(slots=True)
class PersonaMemoryDelta:
    """Cambios incrementales que aun no se han aplicado a `Persona.memory`."""

    liked_uris: list[str] = field(default_factory=list)
    saved_uris: list[str] = field(default_factory=list)
    added_to_playlist_uris: list[str] = field(default_factory=list)
    queued_uris: list[str] = field(default_factory=list)
    followed_artists: list[str] = field(default_factory=list)
    visited_artists: list[str] = field(default_factory=list)
    searches: list[str] = field(default_factory=list)
    streamed_minutes: int = 0
    streams_counted: int = 0

    # ── Mutaciones explicitas (la engine usa estos metodos, no toca campos) ──
    def add_like(self, song_uri: str) -> None:
        if song_uri and song_uri not in self.liked_uris:
            self.liked_uris.append(song_uri)

    def add_save(self, song_uri: str) -> None:
        if song_uri and song_uri not in self.saved_uris:
            self.saved_uris.append(song_uri)

    def add_to_playlist(self, song_uri: str) -> None:
        if song_uri and song_uri not in self.added_to_playlist_uris:
            self.added_to_playlist_uris.append(song_uri)

    def add_to_queue(self, song_uri: str) -> None:
        if song_uri:
            self.queued_uris.append(song_uri)

    def add_follow(self, artist_uri: str) -> None:
        if artist_uri and artist_uri not in self.followed_artists:
            self.followed_artists.append(artist_uri)

    def add_visit_artist(self, artist_uri: str) -> None:
        if artist_uri:
            self.visited_artists.append(artist_uri)

    def add_search(self, query: str) -> None:
        if query:
            self.searches.append(query)

    def add_stream(self, *, minutes: int, counted: bool) -> None:
        self.streamed_minutes += max(minutes, 0)
        if counted:
            self.streams_counted += 1

    # ── Aplicacion ──────────────────────────────────────────────────────────
    def apply_to(self, persona: Persona) -> None:
        """Aplica el delta sobre `persona.memory`.

        Idempotente respecto a sets (likes/saves/follows). En listas con orden
        (recientes) hace append acotado al limite documentado en PersonaMemory.
        """
        memory = persona.memory
        memory.liked_songs.update(self.liked_uris)
        memory.saved_songs.update(self.saved_uris)
        memory.followed_artists.update(self.followed_artists)

        # Recientes: limites suaves para no inflar memoria histórica
        for query in self.searches:
            if query not in memory.recent_searches:
                memory.recent_searches.append(query)
        memory.recent_searches = memory.recent_searches[-50:]

        for artist in self.visited_artists:
            memory.recent_artists_visited.append(artist)
        memory.recent_artists_visited = memory.recent_artists_visited[-100:]

        memory.total_stream_minutes += self.streamed_minutes
        memory.total_streams += self.streams_counted

    def is_empty(self) -> bool:
        """¿Hubo algun cambio relevante en la sesion?"""
        return not any(
            (
                self.liked_uris,
                self.saved_uris,
                self.added_to_playlist_uris,
                self.queued_uris,
                self.followed_artists,
                self.visited_artists,
                self.searches,
                self.streamed_minutes,
                self.streams_counted,
            )
        )
