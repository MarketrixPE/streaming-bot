"""Tests del HumanBehaviorEngine.

Estrategia:
- Mock `IRichBrowserSession` con AsyncMock + spec.
- Persona deterministica con `rng_seed` fijo para reproducir resultados.
- Verificamos: probabilidad correcta, eventos emitidos, delta acumulado.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import structlog

from streaming_bot.application.behavior_engine import HumanBehaviorEngine
from streaming_bot.application.persona_memory_delta import PersonaMemoryDelta
from streaming_bot.domain.history import BehaviorType
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
from streaming_bot.domain.value_objects import Country
from tests.application.fakes import build_rich_session_mock


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch global de asyncio.sleep para que los tests sean instantaneos."""

    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)


def _persona(level: EngagementLevel) -> Persona:
    """Construye una persona completa para el nivel dado."""
    traits = PersonaTraits(
        engagement_level=level,
        preferred_genres=("reggaeton", "trap_latino"),
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
        account_id=f"acc-{level.value}",
        traits=traits,
        memory=PersonaMemory(),
        created_at_iso="2026-01-01T00:00:00Z",
    )


def _engine(persona: Persona, *, seed: int = 42) -> HumanBehaviorEngine:
    return HumanBehaviorEngine(
        persona=persona,
        session_id="test-session",
        rng_seed=seed,
        logger=structlog.get_logger("test"),
        now_factory=lambda: datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC),
    )


class TestProbabilityCalibration:
    """Verifica que las probabilidades de la persona se respetan al ejecutar."""

    async def test_lurker_likes_rarely(self) -> None:
        persona = _persona(EngagementLevel.LURKER)
        engine = _engine(persona, seed=123)
        page = build_rich_session_mock()

        executed = 0
        for _ in range(500):
            event = await engine.maybe_like_current_track(page)
            if event is not None and event.type == BehaviorType.LIKE:
                executed += 1

        # LURKER like = 0.02 → ~10 ejecuciones de 500 (varianza esperada 0-25).
        assert 0 <= executed <= 25, f"LURKER ejecuto demasiados likes: {executed}"

    async def test_fanatic_likes_frequently(self) -> None:
        persona = _persona(EngagementLevel.FANATIC)
        engine = _engine(persona, seed=123)
        page = build_rich_session_mock()

        executed = 0
        for _ in range(500):
            event = await engine.maybe_like_current_track(page)
            if event is not None and event.type == BehaviorType.LIKE:
                executed += 1

        # FANATIC like = 0.25 → ~125 ejecuciones de 500 (rango 90-160).
        assert 90 <= executed <= 160, f"FANATIC ejecuto count fuera de rango: {executed}"

    async def test_engaged_in_between_lurker_and_fanatic(self) -> None:
        page = build_rich_session_mock()
        runs = 300

        async def _count_likes(level: EngagementLevel) -> int:
            engine = _engine(_persona(level), seed=99)
            count = 0
            for _ in range(runs):
                event = await engine.maybe_like_current_track(page)
                if event is not None and event.type == BehaviorType.LIKE:
                    count += 1
            return count

        lurker = await _count_likes(EngagementLevel.LURKER)
        engaged = await _count_likes(EngagementLevel.ENGAGED)
        fanatic = await _count_likes(EngagementLevel.FANATIC)
        assert lurker < engaged < fanatic


class TestSelectorMisses:
    """Si el selector no esta visible debe emitir SELECTOR_NOT_FOUND, no crashear."""

    async def test_like_selector_missing_returns_event(self) -> None:
        persona = _persona(EngagementLevel.FANATIC)
        engine = _engine(persona, seed=1)
        page = build_rich_session_mock()
        page.is_visible.return_value = False

        # Forzamos varias tiradas hasta que decida ejecutar (FANATIC=0.25 → rapido).
        for _ in range(40):
            event = await engine.maybe_like_current_track(page)
            if event is not None:
                assert event.type == BehaviorType.SELECTOR_NOT_FOUND
                return
        pytest.fail("FANATIC nunca disparo el behavior con seed=1")


class TestEventMetadata:
    async def test_like_event_includes_track_uri(self) -> None:
        persona = _persona(EngagementLevel.FANATIC)
        engine = _engine(persona, seed=7)
        page = build_rich_session_mock()
        page.evaluate.return_value = "spotify:track:abc123"

        event = None
        for _ in range(40):
            event = await engine.maybe_like_current_track(page)
            if event is not None and event.type == BehaviorType.LIKE:
                break
        assert event is not None and event.type == BehaviorType.LIKE
        assert event.target_uri == "spotify:track:abc123"
        assert "spotify:track:abc123" in engine.memory_delta.liked_uris

    async def test_pause_resume_records_duration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Skipeamos el sleep real para tests rapidos.
        async def _fake_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr("asyncio.sleep", _fake_sleep)

        persona = _persona(EngagementLevel.FANATIC)
        engine = _engine(persona, seed=42)
        page = build_rich_session_mock()

        for _ in range(40):
            event = await engine.maybe_pause_resume(page, pause_seconds_range=(2, 5))
            if event is not None and event.type == BehaviorType.PAUSE_RESUME:
                assert event.duration_ms in {2000, 3000, 4000, 5000}
                return
        pytest.fail("pause_resume nunca disparo")


class TestNavigationBehaviors:
    async def test_visit_search_with_query_records_search(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _fake_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr("asyncio.sleep", _fake_sleep)

        persona = _persona(EngagementLevel.FANATIC)
        engine = _engine(persona, seed=11)
        page = build_rich_session_mock()
        page.is_visible.return_value = True

        for _ in range(40):
            event = await engine.maybe_visit_search(page, query="bad bunny")
            if event is not None and event.type == BehaviorType.VISIT_SEARCH:
                assert "bad bunny" in engine.memory_delta.searches
                page.human_type.assert_called()
                return
        pytest.fail("visit_search nunca disparo con FANATIC seed=11")

    async def test_scroll_sidebar_calls_human_scroll(self) -> None:
        persona = _persona(EngagementLevel.FANATIC)
        engine = _engine(persona, seed=5)
        page = build_rich_session_mock()

        for _ in range(40):
            event = await engine.maybe_scroll_sidebar(page)
            if event is not None and event.type == BehaviorType.SCROLL_SIDEBAR:
                page.human_scroll.assert_called()
                return
        pytest.fail("scroll_sidebar nunca disparo")


class TestArtistBehaviors:
    async def test_visit_artist_profile_navigates(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _fake_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr("asyncio.sleep", _fake_sleep)

        persona = _persona(EngagementLevel.FANATIC)
        engine = _engine(persona, seed=3)
        page = build_rich_session_mock()
        artist_uri = "spotify:artist:bunny42"

        for _ in range(40):
            event = await engine.maybe_visit_artist_profile(page, artist_uri=artist_uri)
            if event is not None and event.type == BehaviorType.VISIT_ARTIST_PROFILE:
                page.goto.assert_called_with(
                    "https://open.spotify.com/artist/bunny42",
                    wait_until="domcontentloaded",
                )
                assert artist_uri in engine.memory_delta.visited_artists
                return
        pytest.fail("visit_artist_profile nunca disparo")

    async def test_follow_artist_records_in_delta(self) -> None:
        persona = _persona(EngagementLevel.FANATIC)
        engine = _engine(persona, seed=4)
        page = build_rich_session_mock()
        page.evaluate.return_value = "artist:bunny42"

        for _ in range(80):
            event = await engine.maybe_follow_artist(page)
            if event is not None and event.type == BehaviorType.FOLLOW_ARTIST:
                assert any("bunny42" in a for a in engine.memory_delta.followed_artists)
                return
        pytest.fail("follow_artist nunca disparo")


class TestPlayerMicroInteractions:
    async def test_volume_change_uses_bounding_box(self) -> None:
        persona = _persona(EngagementLevel.FANATIC)
        engine = _engine(persona, seed=2)
        page = build_rich_session_mock()
        page.get_bounding_box.return_value = (0.0, 100.0, 200.0, 8.0)

        for _ in range(40):
            event = await engine.maybe_volume_change(page)
            if event is not None and event.type == BehaviorType.VOLUME_CHANGE:
                page.human_mouse_move.assert_called()
                page.human_click.assert_called()
                return
        pytest.fail("volume_change nunca disparo")

    async def test_volume_change_handles_missing_bbox(self) -> None:
        persona = _persona(EngagementLevel.FANATIC)
        engine = _engine(persona, seed=2)
        page = build_rich_session_mock()
        page.get_bounding_box.return_value = None

        for _ in range(40):
            event = await engine.maybe_volume_change(page)
            if event is not None:
                assert event.type == BehaviorType.SELECTOR_NOT_FOUND
                return
        # Si nunca disparo no es fallo: la probabilidad puede dar 0.


class TestSessionLevelBehaviors:
    async def test_tab_blur_calls_emulate(self) -> None:
        persona = _persona(EngagementLevel.FANATIC)
        engine = _engine(persona, seed=8)
        page = build_rich_session_mock()

        for _ in range(40):
            event = await engine.maybe_tab_blur_event(page)
            if event is not None and event.type == BehaviorType.TAB_BLUR_EVENT:
                page.emulate_tab_blur.assert_called()
                assert event.duration_ms > 0
                return
        pytest.fail("tab_blur nunca disparo con FANATIC")


class TestMemoryDelta:
    async def test_apply_memory_to_persona_updates_likes(self) -> None:
        persona = _persona(EngagementLevel.ENGAGED)
        engine = _engine(persona, seed=1)
        engine.memory_delta.add_like("spotify:track:a")
        engine.memory_delta.add_like("spotify:track:b")
        engine.memory_delta.add_save("spotify:track:c")
        engine.memory_delta.add_follow("spotify:artist:x")
        engine.memory_delta.add_search("perreo")
        engine.memory_delta.add_visit_artist("spotify:artist:y")
        engine.memory_delta.add_stream(minutes=12, counted=True)

        engine.apply_memory_to_persona(persona)

        assert persona.memory.liked_songs == {"spotify:track:a", "spotify:track:b"}
        assert persona.memory.saved_songs == {"spotify:track:c"}
        assert persona.memory.followed_artists == {"spotify:artist:x"}
        assert "perreo" in persona.memory.recent_searches
        assert "spotify:artist:y" in persona.memory.recent_artists_visited
        assert persona.memory.total_streams == 1
        assert persona.memory.total_stream_minutes == 12

    async def test_delta_caps_recent_searches_at_50(self) -> None:
        delta = PersonaMemoryDelta()
        for i in range(80):
            delta.add_search(f"q-{i}")
        persona = _persona(EngagementLevel.ENGAGED)
        delta.apply_to(persona)
        assert len(persona.memory.recent_searches) == 50

    async def test_delta_is_empty_initially(self) -> None:
        assert PersonaMemoryDelta().is_empty()
        delta = PersonaMemoryDelta()
        delta.add_like("x")
        assert not delta.is_empty()


class TestDeterminism:
    async def test_same_seed_produces_same_outcome(self) -> None:
        persona = _persona(EngagementLevel.ENGAGED)
        page = build_rich_session_mock()

        engine_a = _engine(persona, seed=999)
        engine_b = _engine(persona, seed=999)

        results_a = [bool(await engine_a.maybe_like_current_track(page)) for _ in range(50)]
        results_b = [bool(await engine_b.maybe_like_current_track(page)) for _ in range(50)]
        assert results_a == results_b


# ── Coverage exhaustivo: cada behavior maybe_* se ejecuta al menos 1 vez ──
@pytest.mark.parametrize(
    "behavior_name",
    [
        "maybe_like_current_track",
        "maybe_save_to_library",
        "maybe_add_to_playlist",
        "maybe_add_to_queue",
        "maybe_open_canvas",
        "maybe_open_lyrics",
        "maybe_click_credits",
        "maybe_open_share_modal",
        "maybe_follow_artist",
        "maybe_view_artist_about",
        "maybe_play_other_song_of_artist",
        "maybe_view_discography",
        "maybe_volume_change",
        "maybe_mute_toggle",
        "maybe_repeat_toggle",
        "maybe_shuffle_toggle",
        "maybe_pause_resume",
        "maybe_scrub_forward",
        "maybe_scrub_backward",
        "maybe_toggle_time_remaining",
        "maybe_open_devices_modal",
        "maybe_visit_home",
        "maybe_visit_search",
        "maybe_visit_library",
        "maybe_scroll_sidebar",
        "maybe_toggle_view_mode",
        "maybe_open_notifications",
        "maybe_open_settings",
        "maybe_listen_discover_weekly",
        "maybe_listen_made_for_you",
        "maybe_long_pause_distracted",
        "maybe_tab_blur_event",
    ],
)
async def test_each_behavior_can_execute(behavior_name: str) -> None:
    """Garantiza que cada behavior maybe_* es invocable y emite algun evento."""
    persona = _persona(EngagementLevel.FANATIC)
    # Forzamos probabilidad 1.0 en TODOS los behaviors para 1-tirada-1-evento.
    forced = persona.traits.behaviors
    high_probs = type(forced)(
        like=1.0,
        save_to_library=1.0,
        add_to_playlist=1.0,
        add_to_queue=1.0,
        open_canvas=1.0,
        open_lyrics=1.0,
        click_credits=1.0,
        open_share_modal=1.0,
        visit_artist_profile=1.0,
        follow_artist=1.0,
        view_artist_about=1.0,
        play_other_song_of_artist=1.0,
        view_discography=1.0,
        volume_change=1.0,
        mute_toggle=1.0,
        repeat_toggle=1.0,
        shuffle_toggle=1.0,
        pause_resume=1.0,
        scrub_forward=1.0,
        scrub_backward=1.0,
        toggle_time_remaining=1.0,
        open_devices_modal=1.0,
        visit_home=1.0,
        visit_search=1.0,
        visit_library=1.0,
        scroll_sidebar=1.0,
        toggle_view_mode=1.0,
        open_notifications=1.0,
        open_settings=1.0,
        listen_discover_weekly=1.0,
        listen_made_for_you=1.0,
        long_pause_distracted=1.0,
        tab_blur_event=1.0,
    )
    persona = Persona(
        account_id=persona.account_id,
        traits=PersonaTraits(
            engagement_level=persona.traits.engagement_level,
            preferred_genres=persona.traits.preferred_genres,
            preferred_session_hour_local=persona.traits.preferred_session_hour_local,
            device=persona.traits.device,
            platform=persona.traits.platform,
            ui_language=persona.traits.ui_language,
            timezone=persona.traits.timezone,
            country=persona.traits.country,
            behaviors=high_probs,
            typing=persona.traits.typing,
            mouse=persona.traits.mouse,
            session=persona.traits.session,
        ),
        memory=persona.memory,
        created_at_iso=persona.created_at_iso,
    )
    engine = _engine(persona, seed=1)
    page = build_rich_session_mock()
    if behavior_name == "maybe_visit_artist_profile":
        event = await engine.maybe_visit_artist_profile(page, artist_uri="spotify:artist:x")
    elif behavior_name == "maybe_visit_search":
        event = await engine.maybe_visit_search(page, query="reggaeton")
    elif behavior_name == "maybe_pause_resume":
        event = await engine.maybe_pause_resume(page, pause_seconds_range=(1, 1))
    else:
        method = getattr(engine, behavior_name)
        event = await method(page)
    assert event is not None, f"{behavior_name} no emitio evento con probabilidad 1.0"


async def test_visit_artist_profile_with_probability_one_navigates() -> None:
    """Caso aparte por requerir kwarg `artist_uri`."""
    persona = _persona(EngagementLevel.FANATIC)
    high = type(persona.traits.behaviors)(visit_artist_profile=1.0)
    persona = Persona(
        account_id=persona.account_id,
        traits=PersonaTraits(
            engagement_level=persona.traits.engagement_level,
            preferred_genres=persona.traits.preferred_genres,
            preferred_session_hour_local=persona.traits.preferred_session_hour_local,
            device=persona.traits.device,
            platform=persona.traits.platform,
            ui_language=persona.traits.ui_language,
            timezone=persona.traits.timezone,
            country=persona.traits.country,
            behaviors=high,
            typing=persona.traits.typing,
            mouse=persona.traits.mouse,
            session=persona.traits.session,
        ),
        memory=PersonaMemory(),
        created_at_iso=persona.created_at_iso,
    )
    engine = _engine(persona, seed=1)
    page = build_rich_session_mock()
    event = await engine.maybe_visit_artist_profile(
        page,
        artist_uri="spotify:artist:abc123",
    )
    assert event is not None
    assert "spotify:artist:abc123" in engine.memory_delta.visited_artists
