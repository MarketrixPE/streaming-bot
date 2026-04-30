"""Fixtures y mocks reutilizables para tests de la capa de aplicacion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from streaming_bot.domain.entities import Account, AccountStatus
from streaming_bot.domain.persona import (
    BehaviorProbabilities,
    DeviceType,
    EngagementLevel,
    MouseProfile,
    Persona,
    PersonaMemory,
    PersonaTraits,
    PlatformProfile,
    SessionPattern,
    TypingProfile,
)
from streaming_bot.domain.playlist import (
    Playlist,
    PlaylistKind,
    PlaylistTrack,
    PlaylistVisibility,
)
from streaming_bot.domain.value_objects import (
    Country,
    Fingerprint,
    GeoCoordinate,
    ProxyEndpoint,
)


def build_rich_session_mock(
    *,
    track_uri: str = "spotify:track:abc",
    visible: bool = True,
    bbox: tuple[float, float, float, float] | None = (0.0, 0.0, 200.0, 8.0),
) -> AsyncMock:
    """Construye un mock de IRichBrowserSession con defaults razonables."""
    page = AsyncMock()
    page.is_visible.return_value = visible
    page.evaluate.return_value = track_uri
    page.get_bounding_box.return_value = bbox
    page.query_selector_count.return_value = 5
    page.get_text.return_value = "Mock Track"
    page.get_viewport_size.return_value = (1366, 768)
    page.current_url.return_value = "https://open.spotify.com/"
    page.storage_state.return_value = {"cookies": [], "origins": []}
    return page


def build_persona(level: EngagementLevel = EngagementLevel.ENGAGED) -> Persona:
    """Persona completa con comportamientos calibrados por nivel."""
    traits = PersonaTraits(
        engagement_level=level,
        preferred_genres=("reggaeton",),
        preferred_session_hour_local=(18, 23),
        device=DeviceType.DESKTOP_CHROME,
        platform=PlatformProfile.WINDOWS_DESKTOP,
        ui_language="es-PE",
        timezone="America/Lima",
        country=Country.PE,
        behaviors=BehaviorProbabilities.for_engagement_level(level),
        typing=TypingProfile(),
        mouse=MouseProfile(),
        session=SessionPattern(),
    )
    return Persona(
        account_id="acc-1",
        traits=traits,
        memory=PersonaMemory(),
        created_at_iso=datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
    )


def build_account(country: Country = Country.PE, *, banned: bool = False) -> Account:
    return Account(
        id="acc-1",
        username="user",
        password="pass",
        country=country,
        status=AccountStatus.banned("test") if banned else AccountStatus.active(),
    )


def build_playlist(
    *,
    target_uris: tuple[str, ...] = ("spotify:track:t1",),
    track_count: int = 5,
) -> Playlist:
    playlist = Playlist.new(
        name="test",
        kind=PlaylistKind.PROJECT_PUBLIC,
        visibility=PlaylistVisibility.PUBLIC,
        territory=Country.PE,
        genre="reggaeton",
    )
    playlist.spotify_id = "spotify-pl-1"
    for i in range(track_count):
        uri = target_uris[i] if i < len(target_uris) else f"spotify:track:cam{i}"
        playlist.add_track(
            PlaylistTrack(
                track_uri=uri,
                position=i,
                is_target=uri in target_uris,
                duration_ms=180_000,
                artist_uri=f"spotify:artist:a{i}",
                title=f"Track {i}",
            )
        )
    return playlist


def build_fingerprint() -> Fingerprint:
    return Fingerprint(
        user_agent="Mozilla/5.0",
        locale="es-PE",
        timezone_id="America/Lima",
        geolocation=GeoCoordinate(-12.04, -77.04),
        country=Country.PE,
    )


def build_proxy() -> ProxyEndpoint:
    return ProxyEndpoint(
        scheme="http",
        host="proxy.test",
        port=8080,
        country=Country.PE,
    )


def build_use_case_mocks(persona: Persona, playlist: Playlist) -> dict[str, Any]:
    """Ensambla un diccionario de mocks listo para inyectar al use case."""
    accounts = AsyncMock()
    accounts.get.return_value = build_account()
    accounts.update.return_value = None

    sessions = AsyncMock()
    sessions.load.return_value = None
    sessions.save.return_value = None
    sessions.delete.return_value = None

    proxies = AsyncMock()
    proxies.acquire.return_value = build_proxy()
    proxies.report_success.return_value = None
    proxies.report_failure.return_value = None

    fingerprints = MagicMock()
    fingerprints.coherent_for.return_value = build_fingerprint()

    personas = AsyncMock()
    personas.get.return_value = persona
    personas.update_memory.return_value = None

    playlists = AsyncMock()
    playlists.get.return_value = playlist

    songs = AsyncMock()
    history = AsyncMock()
    session_records = AsyncMock()

    page = build_rich_session_mock()

    class _Session:
        async def __aenter__(self) -> AsyncMock:
            return page

        async def __aexit__(self, *_a: object) -> None:
            return None

    browser = MagicMock()
    browser.session = MagicMock(return_value=_Session())

    strategy = AsyncMock()
    strategy.is_logged_in.return_value = True
    strategy.login.return_value = None
    strategy.wait_for_player_ready.return_value = None
    strategy.get_current_track_uri.side_effect = lambda _p: None
    strategy.get_current_artist_uri.return_value = None

    return {
        "accounts": accounts,
        "sessions": sessions,
        "proxies": proxies,
        "fingerprints": fingerprints,
        "personas": personas,
        "songs": songs,
        "playlists": playlists,
        "history": history,
        "session_records": session_records,
        "browser": browser,
        "page": page,
        "strategy": strategy,
    }
