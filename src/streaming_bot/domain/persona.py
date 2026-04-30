"""Persona persistente de cada cuenta.

Una `Persona` define el "carácter" estable de una cuenta: nivel de engagement,
géneros preferidos, dispositivo, hora típica, probabilidades de comportamientos
humanos. La persona NO cambia entre sesiones; lo que evoluciona es la `Memory`
(libreria de likes, follows, playlists, etc.) que crece orgánicamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import Enum

from streaming_bot.domain.value_objects import Country


class EngagementLevel(str, Enum):
    """Nivel base de engagement de la cuenta. Define probabilidades por defecto."""

    LURKER = "lurker"  # like ~2%, save ~3%, follow ~0.5%
    CASUAL = "casual"  # like ~8%, save ~12%, follow ~3%
    ENGAGED = "engaged"  # like ~15%, save ~22%, follow ~6%
    FANATIC = "fanatic"  # like ~25%, save ~35%, follow ~12%


class DeviceType(str, Enum):
    """Dispositivo simulado. Afecta UA, viewport, capabilities."""

    DESKTOP_CHROME = "desktop_chrome"
    DESKTOP_FIREFOX = "desktop_firefox"
    DESKTOP_EDGE = "desktop_edge"
    WEB_PLAYER_MOBILE = "web_player_mobile"  # Chrome mobile UA en desktop


class PlatformProfile(str, Enum):
    """Combinación OS + plataforma para coherencia de fingerprint."""

    WINDOWS_DESKTOP = "windows_desktop"
    MACOS_DESKTOP = "macos_desktop"
    LINUX_DESKTOP = "linux_desktop"
    ANDROID_MOBILE = "android_mobile"
    IOS_MOBILE = "ios_mobile"


@dataclass(frozen=True, slots=True)
class BehaviorProbabilities:
    """Probabilidades de cada behavior. Suma no necesariamente 1 (independientes)."""

    # Engagement con canción target
    like: float = 0.08
    save_to_library: float = 0.12
    add_to_playlist: float = 0.04
    add_to_queue: float = 0.03
    open_canvas: float = 0.25
    open_lyrics: float = 0.15
    click_credits: float = 0.01
    open_share_modal: float = 0.02

    # Engagement con artista
    visit_artist_profile: float = 0.10
    follow_artist: float = 0.03
    view_artist_about: float = 0.02
    play_other_song_of_artist: float = 0.05
    view_discography: float = 0.04

    # Player micro-interacciones
    volume_change: float = 0.18
    mute_toggle: float = 0.04
    repeat_toggle: float = 0.06
    shuffle_toggle: float = 0.08
    pause_resume: float = 0.12
    scrub_forward: float = 0.05  # adelantar a 70-90%
    scrub_backward: float = 0.08  # volver a parte favorita
    toggle_time_remaining: float = 0.03
    open_devices_modal: float = 0.01

    # Navegación global
    visit_home: float = 0.15
    visit_search: float = 0.20
    visit_library: float = 0.10
    scroll_sidebar: float = 0.30
    toggle_view_mode: float = 0.05
    open_notifications: float = 0.04
    open_settings: float = 0.03

    # Sesión nivel
    listen_discover_weekly: float = 0.20  # 1 vez por sesión típica
    listen_made_for_you: float = 0.20
    long_pause_distracted: float = 0.08  # pausa de 3-15 min
    tab_blur_event: float = 0.30  # cambia a otra ventana

    @classmethod
    def for_engagement_level(cls, level: EngagementLevel) -> BehaviorProbabilities:
        """Devuelve probabilidades calibradas para un nivel."""
        match level:
            case EngagementLevel.LURKER:
                return cls(
                    like=0.02,
                    save_to_library=0.03,
                    add_to_playlist=0.01,
                    follow_artist=0.005,
                    visit_artist_profile=0.04,
                    volume_change=0.10,
                    pause_resume=0.05,
                    scrub_backward=0.02,
                    visit_search=0.10,
                    visit_library=0.04,
                )
            case EngagementLevel.ENGAGED:
                return cls(
                    like=0.15,
                    save_to_library=0.22,
                    add_to_playlist=0.08,
                    follow_artist=0.06,
                    visit_artist_profile=0.18,
                    volume_change=0.25,
                    pause_resume=0.18,
                    scrub_backward=0.15,
                    visit_search=0.30,
                    visit_library=0.20,
                )
            case EngagementLevel.FANATIC:
                return cls(
                    like=0.25,
                    save_to_library=0.35,
                    add_to_playlist=0.15,
                    follow_artist=0.12,
                    visit_artist_profile=0.30,
                    volume_change=0.35,
                    pause_resume=0.25,
                    scrub_backward=0.25,
                    visit_search=0.40,
                    visit_library=0.30,
                )
            case EngagementLevel.CASUAL:
                return cls()


@dataclass(frozen=True, slots=True)
class TypingProfile:
    """Perfil de tipeo humano para campos de texto."""

    avg_wpm: int = 70  # words per minute promedio
    wpm_stddev: int = 15  # varianza
    typo_probability_per_word: float = 0.03
    pause_probability_between_words: float = 0.10  # micro-pausas

    def chars_per_second(self) -> float:
        """Convierte WPM a chars/s asumiendo 5 chars/word promedio."""
        return self.avg_wpm * 5.0 / 60.0


@dataclass(frozen=True, slots=True)
class MouseProfile:
    """Perfil de movimiento del cursor."""

    bezier_control_points: int = 3  # complejidad de la curva
    velocity_stddev: float = 0.25  # varianza de velocidad
    overshoot_probability: float = 0.30  # 30% de clicks overshoot+correct
    overshoot_pixels_max: int = 15
    pre_click_hover_ms_min: int = 100
    pre_click_hover_ms_max: int = 400
    reading_time_ms_min: int = 200  # antes de click decisivo
    reading_time_ms_max: int = 800


@dataclass(frozen=True, slots=True)
class SessionPattern:
    """Cómo estructura sus sesiones la cuenta."""

    avg_streams_per_session: int = 8
    streams_per_session_stddev: int = 3
    avg_session_minutes: int = 50
    session_minutes_stddev: int = 20
    sessions_per_day_min: int = 1
    sessions_per_day_max: int = 3
    skip_rate_min: float = 0.05
    skip_rate_max: float = 0.20
    target_catalog_ratio: float = 0.30  # 30% canciones target / 70% camuflaje


@dataclass(frozen=True, slots=True)
class PersonaTraits:
    """Características inmutables que definen la persona."""

    engagement_level: EngagementLevel
    preferred_genres: tuple[str, ...]
    preferred_session_hour_local: tuple[int, int]  # (start_hour, end_hour) 0-23
    device: DeviceType
    platform: PlatformProfile
    ui_language: str  # "es-PE", "es-MX", "en-US", etc.
    timezone: str  # "America/Lima", "America/Mexico_City"
    country: Country
    behaviors: BehaviorProbabilities
    typing: TypingProfile
    mouse: MouseProfile
    session: SessionPattern

    def is_active_at_local_hour(self, hour: int) -> bool:
        """¿La persona estaría online a esta hora local?"""
        start, end = self.preferred_session_hour_local
        if start <= end:
            return start <= hour <= end
        return hour >= start or hour <= end


@dataclass(slots=True)
class PersonaMemory:
    """Memoria evolutiva. Lo que la cuenta ha hecho a lo largo del tiempo.

    Crece de forma orgánica para que cada cuenta tenga historial coherente.
    """

    liked_songs: set[str] = field(default_factory=set)  # spotify URIs
    saved_songs: set[str] = field(default_factory=set)
    followed_artists: set[str] = field(default_factory=set)
    followed_playlists: set[str] = field(default_factory=set)
    own_playlists: list[str] = field(default_factory=list)  # IDs de playlists creadas
    recent_searches: list[str] = field(default_factory=list)  # cap 50
    recent_artists_visited: list[str] = field(default_factory=list)  # cap 100
    total_stream_minutes: int = 0
    total_streams: int = 0

    def has_liked(self, song_uri: str) -> bool:
        return song_uri in self.liked_songs

    def has_saved(self, song_uri: str) -> bool:
        return song_uri in self.saved_songs

    def has_followed(self, artist_uri: str) -> bool:
        return artist_uri in self.followed_artists


@dataclass(slots=True)
class Persona:
    """Persona completa = traits inmutables + memoria evolutiva."""

    account_id: str
    traits: PersonaTraits
    memory: PersonaMemory = field(default_factory=PersonaMemory)
    created_at_iso: str = ""
    last_session_at_iso: str | None = None

    @property
    def country(self) -> Country:
        return self.traits.country

    @property
    def timezone(self) -> str:
        return self.traits.timezone

    @property
    def language(self) -> str:
        return self.traits.ui_language

    def session_window_local(self) -> tuple[time, time]:
        """Hora local de inicio y fin típica de sesión."""
        start_h, end_h = self.traits.preferred_session_hour_local
        return time(hour=start_h), time(hour=end_h)
