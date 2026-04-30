"""Historial granular de streams y sesiones para auditoría y scheduling.

Este módulo provee las entidades que el scheduler consulta para:
- Saber qué cuenta puede tocar qué canción y cuándo (cooldown)
- Detectar patrones sospechosos antes que Beatdapp
- Reportar a Grafana el throughput real
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import uuid4


class BehaviorType(str, Enum):
    """Cada acción humana ejecutada en una sesión.

    El BehaviorEngine reporta estos eventos durante la ejecución y se persisten
    para auditoría. Útil para entender qué patrones pasan vs son detectados.
    """

    # Engagement con canción target
    LIKE = "like"
    SAVE_TO_LIBRARY = "save_to_library"
    ADD_TO_PLAYLIST = "add_to_playlist"
    ADD_TO_QUEUE = "add_to_queue"
    OPEN_CANVAS = "open_canvas"
    OPEN_LYRICS = "open_lyrics"
    CLICK_CREDITS = "click_credits"
    OPEN_SHARE_MODAL = "open_share_modal"

    # Engagement con artista
    VISIT_ARTIST_PROFILE = "visit_artist_profile"
    FOLLOW_ARTIST = "follow_artist"
    VIEW_ARTIST_ABOUT = "view_artist_about"
    PLAY_OTHER_SONG_OF_ARTIST = "play_other_song_of_artist"
    VIEW_DISCOGRAPHY = "view_discography"

    # Player micro
    VOLUME_CHANGE = "volume_change"
    MUTE_TOGGLE = "mute_toggle"
    REPEAT_TOGGLE = "repeat_toggle"
    SHUFFLE_TOGGLE = "shuffle_toggle"
    PAUSE_RESUME = "pause_resume"
    SCRUB_FORWARD = "scrub_forward"
    SCRUB_BACKWARD = "scrub_backward"
    TOGGLE_TIME_REMAINING = "toggle_time_remaining"
    OPEN_DEVICES_MODAL = "open_devices_modal"

    # Navegación global
    VISIT_HOME = "visit_home"
    VISIT_SEARCH = "visit_search"
    VISIT_LIBRARY = "visit_library"
    SCROLL_SIDEBAR = "scroll_sidebar"
    TOGGLE_VIEW_MODE = "toggle_view_mode"
    OPEN_NOTIFICATIONS = "open_notifications"
    OPEN_SETTINGS = "open_settings"

    # Sesión nivel
    LISTEN_DISCOVER_WEEKLY = "listen_discover_weekly"
    LISTEN_MADE_FOR_YOU = "listen_made_for_you"
    LONG_PAUSE_DISTRACTED = "long_pause_distracted"
    TAB_BLUR_EVENT = "tab_blur_event"

    # Stream lifecycle (siempre presentes)
    STREAM_START = "stream_start"
    STREAM_30S_THRESHOLD = "stream_30s_threshold"
    STREAM_COMPLETE = "stream_complete"
    STREAM_SKIPPED = "stream_skipped"

    # Errores
    SELECTOR_NOT_FOUND = "selector_not_found"
    CAPTCHA_DETECTED = "captcha_detected"
    LOGIN_REQUIRED = "login_required"


class StreamOutcome(str, Enum):
    """Resultado de un intento de stream."""

    COUNTED = "counted"  # >30s, contó como play válido
    PARTIAL = "partial"  # <30s, no cuenta
    SKIPPED = "skipped"  # usuario hizo skip
    FAILED = "failed"  # error técnico
    BLOCKED = "blocked"  # cuenta baneada o captcha
    PENDING = "pending"  # aún en curso


@dataclass(frozen=True, slots=True)
class BehaviorEvent:
    """Un evento atómico ejecutado dentro de una sesión."""

    event_id: str
    session_id: str
    type: BehaviorType
    occurred_at: datetime
    target_uri: str | None = None  # URI de canción/artista/playlist afectado
    duration_ms: int = 0
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def new(
        cls,
        *,
        session_id: str,
        type: BehaviorType,
        occurred_at: datetime,
        target_uri: str | None = None,
        duration_ms: int = 0,
        metadata: dict[str, str] | None = None,
    ) -> BehaviorEvent:
        return cls(
            event_id=str(uuid4()),
            session_id=session_id,
            type=type,
            occurred_at=occurred_at,
            target_uri=target_uri,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )


@dataclass(slots=True)
class StreamHistory:
    """Cada vez que una cuenta intentó streamear una canción.

    Indexado por (account_id, song_uri, occurred_at) en Postgres.
    Sirve para enforce de cooldown 72h entre cuenta-canción.
    """

    history_id: str
    account_id: str
    song_uri: str
    artist_uri: str
    occurred_at: datetime
    duration_listened_seconds: int
    outcome: StreamOutcome
    proxy_country: str | None = None
    proxy_ip_hash: str | None = None  # hash de IP, no IP raw
    session_id: str | None = None
    error_class: str | None = None  # nombre de excepción si failed

    @classmethod
    def new(
        cls,
        *,
        account_id: str,
        song_uri: str,
        artist_uri: str,
        occurred_at: datetime,
        duration_listened_seconds: int = 0,
        outcome: StreamOutcome = StreamOutcome.PENDING,
        session_id: str | None = None,
    ) -> StreamHistory:
        return cls(
            history_id=str(uuid4()),
            account_id=account_id,
            song_uri=song_uri,
            artist_uri=artist_uri,
            occurred_at=occurred_at,
            duration_listened_seconds=duration_listened_seconds,
            outcome=outcome,
            session_id=session_id,
        )

    @property
    def counted(self) -> bool:
        return self.outcome == StreamOutcome.COUNTED


@dataclass(slots=True)
class SessionRecord:
    """Una sesión completa de una cuenta.

    Una sesión típica dura 30-90 min, contiene 6-15 streams + behaviors.
    """

    session_id: str
    account_id: str
    started_at: datetime
    ended_at: datetime | None = None
    proxy_country: str | None = None
    proxy_ip_hash: str | None = None
    user_agent: str | None = None
    target_streams_attempted: int = 0
    camouflage_streams_attempted: int = 0
    streams_counted: int = 0
    skips: int = 0
    likes_given: int = 0
    saves_given: int = 0
    follows_given: int = 0
    behavior_events: list[BehaviorEvent] = field(default_factory=list)
    error_class: str | None = None
    completed_normally: bool = False

    @classmethod
    def new(
        cls,
        *,
        account_id: str,
        started_at: datetime,
        proxy_country: str | None = None,
        proxy_ip_hash: str | None = None,
        user_agent: str | None = None,
    ) -> SessionRecord:
        return cls(
            session_id=str(uuid4()),
            account_id=account_id,
            started_at=started_at,
            proxy_country=proxy_country,
            proxy_ip_hash=proxy_ip_hash,
            user_agent=user_agent,
        )

    def add_event(self, event: BehaviorEvent) -> None:
        self.behavior_events.append(event)

    def duration_seconds(self) -> int:
        if self.ended_at is None:
            return 0
        return int((self.ended_at - self.started_at).total_seconds())
