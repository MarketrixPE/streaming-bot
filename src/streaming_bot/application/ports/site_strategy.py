"""Puertos ISiteStrategy (basico) e IRichSiteStrategy (con helpers de player).

ISiteStrategy: contrato minimo que debe cumplir cualquier estrategia de
sitio enchufable a StreamSongUseCase (login + perform_action + is_logged_in).

IRichSiteStrategy: extiende el anterior anadiendo los helpers que
PlaylistSessionUseCase necesita para sincronizarse con el player y leer
el track/artista en curso sin acoplar el use case a Spotify-specifics.

Anteriormente ISiteStrategy vivia dentro de application.stream_song y
playlist_session.py tipaba directamente contra SpotifyWebPlayerStrategy
(presentation): fuga de capas. Al consolidar ambos puertos aqui, los use
cases dependen solo de la capa application/ports y las implementaciones
concretas viven en presentation o infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from streaming_bot.domain.entities import Account
    from streaming_bot.domain.ports.browser import IBrowserSession
    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession


@runtime_checkable
class ISiteStrategy(Protocol):
    """Estrategia especifica del sitio objetivo. Cumple OCP: nuevos sitios
    se anaden creando una nueva estrategia, sin modificar el caso de uso.
    """

    async def is_logged_in(self, page: IBrowserSession) -> bool: ...

    async def login(self, page: IBrowserSession, account: Account) -> None: ...

    async def perform_action(
        self,
        page: IBrowserSession,
        target_url: str,
        listen_seconds: int,
    ) -> None: ...


@runtime_checkable
class IRichSiteStrategy(ISiteStrategy, Protocol):
    """Estrategia de sitio para flujos playlist-first con behaviors humanos.

    Anade al ISiteStrategy basico (login + perform_action) los helpers que
    PlaylistSessionUseCase necesita para sincronizarse con el player y leer
    el track/artista en curso sin acoplar el use case a Spotify-specifics.
    """

    async def wait_for_player_ready(self, page: IRichBrowserSession) -> None:
        """Bloquea hasta que el reproductor del sitio este listo para emitir
        controles (track cargado, controles montados).

        Lanza TargetSiteError si no llega a ready en un tiempo razonable.
        """
        ...

    async def get_current_track_uri(self, page: IRichBrowserSession) -> str | None:
        """Devuelve el URI canonico del track actualmente en reproduccion.

        Devuelve None si no se puede leer (transicion entre tracks, error DOM).
        Nunca lanza.
        """
        ...

    async def get_current_artist_uri(self, page: IRichBrowserSession) -> str | None:
        """Devuelve el URI canonico del artista del track actual.

        Devuelve None si no se puede leer. Nunca lanza.
        """
        ...
