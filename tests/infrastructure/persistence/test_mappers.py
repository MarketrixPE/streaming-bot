"""Round-trip puro de mappers domain<->model.

No tocan la BD: convierten objeto-a-objeto y verifican igualdad estructural
de los campos persistidos. Documentan explícitamente qué campos no se
preservan (ver `to_domain_session_record` para la lista).
"""

from __future__ import annotations

from datetime import UTC, datetime

from streaming_bot.domain.entities import Account, AccountStatus
from streaming_bot.domain.history import (
    BehaviorEvent,
    BehaviorType,
    SessionRecord,
    StreamHistory,
    StreamOutcome,
)
from streaming_bot.domain.modem import Modem, ModemHardware, ModemState
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
from streaming_bot.domain.song import Distributor, Song, SongMetadata, SongRole
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.repos.mappers import (
    from_domain_account,
    from_domain_modem,
    from_domain_persona,
    from_domain_playlist,
    from_domain_session_record,
    from_domain_song,
    from_domain_stream_history,
    memory_snapshot_from_domain,
    to_domain_account,
    to_domain_modem,
    to_domain_persona,
    to_domain_playlist,
    to_domain_session_record,
    to_domain_song,
    to_domain_stream_history,
)


def test_account_round_trip() -> None:
    original = Account(
        id="acc-1",
        username="alice",
        password="cipher",
        country=Country.PE,
        status=AccountStatus.banned("captcha"),
        last_used_at=datetime(2026, 4, 27, tzinfo=UTC),
    )

    restored = to_domain_account(from_domain_account(original))

    assert restored == original


def test_song_round_trip_preserves_persisted_fields() -> None:
    original = Song(
        spotify_uri="spotify:track:rt",
        title="Round Trip",
        artist_name="Tony Jaxx",
        artist_uri="spotify:artist:1",
        role=SongRole.TARGET,
        metadata=SongMetadata(duration_seconds=210, isrc="ISRC1"),
        distributor=Distributor.ONERPM,
        baseline_streams_per_day=80.0,
        target_streams_per_day=320,
        top_country_distribution={Country.PE: 0.5, Country.MX: 0.3},
    )

    restored = to_domain_song(from_domain_song(original))

    assert restored.spotify_uri == original.spotify_uri
    assert restored.title == original.title
    assert restored.role == original.role
    assert restored.metadata.isrc == "ISRC1"
    assert restored.metadata.duration_seconds == 210
    assert restored.distributor == Distributor.ONERPM
    assert restored.top_country_distribution == original.top_country_distribution


def test_persona_round_trip_with_snapshot() -> None:
    traits = PersonaTraits(
        engagement_level=EngagementLevel.FANATIC,
        preferred_genres=("perreo",),
        preferred_session_hour_local=(20, 23),
        device=DeviceType.DESKTOP_FIREFOX,
        platform=PlatformProfile.WINDOWS_DESKTOP,
        ui_language="es-MX",
        timezone="America/Mexico_City",
        country=Country.MX,
        behaviors=BehaviorProbabilities.for_engagement_level(EngagementLevel.FANATIC),
        typing=TypingProfile(),
        mouse=MouseProfile(),
        session=SessionPattern(),
    )
    original = Persona(
        account_id="acc-mx",
        traits=traits,
        memory=PersonaMemory(
            liked_songs={"a", "b"},
            saved_songs={"c"},
            recent_searches=["ñ"],
        ),
        created_at_iso="2026-04-27T07:00:00+00:00",
    )

    model = from_domain_persona(original)
    snapshot = memory_snapshot_from_domain(original, snapshot_at=datetime.now(UTC))
    restored = to_domain_persona(model, snapshot)

    assert restored.account_id == original.account_id
    assert restored.traits.engagement_level == EngagementLevel.FANATIC
    assert restored.traits.preferred_genres == ("perreo",)
    assert restored.memory.liked_songs == {"a", "b"}
    assert restored.memory.recent_searches == ["ñ"]


def test_modem_round_trip() -> None:
    hw = ModemHardware(
        imei="999999999999999",
        iccid="89510041000000000099",
        model="Quectel EG25-G",
        serial_port="/dev/ttyUSB0",
        operator="Movistar PE",
        sim_country=Country.PE,
    )
    original = Modem.new(hardware=hw)
    original.state = ModemState.IN_USE
    original.streams_served_today = 17

    restored = to_domain_modem(from_domain_modem(original))

    assert restored.id == original.id
    assert restored.hardware == hw
    assert restored.state == ModemState.IN_USE
    assert restored.streams_served_today == 17


def test_playlist_round_trip() -> None:
    original = Playlist.new(
        name="Round Trip",
        kind=PlaylistKind.PERSONAL_PRIVATE,
        visibility=PlaylistVisibility.PRIVATE,
        territory=Country.PE,
        genre="reggaeton",
    )
    original.add_track(
        PlaylistTrack(
            track_uri="spotify:track:1",
            position=0,
            is_target=True,
            duration_ms=200_000,
            artist_uri="spotify:artist:tj",
            title="T1",
        ),
    )

    restored = to_domain_playlist(from_domain_playlist(original))

    assert restored.id == original.id
    assert restored.name == original.name
    assert restored.kind == original.kind
    assert len(restored.tracks) == 1
    assert restored.tracks[0].track_uri == "spotify:track:1"
    assert restored.tracks[0].is_target is True


def test_stream_history_round_trip() -> None:
    original = StreamHistory(
        history_id="h-1",
        account_id="acc-1",
        song_uri="spotify:track:rt",
        artist_uri="spotify:artist:tj",
        occurred_at=datetime(2026, 4, 27, 18, 0, tzinfo=UTC),
        duration_listened_seconds=45,
        outcome=StreamOutcome.COUNTED,
        proxy_country="PE",
        proxy_ip_hash="hash-abc",
        session_id="sess-1",
    )

    model = from_domain_stream_history(original, song_id="ulid-1")
    restored = to_domain_stream_history(
        model,
        song_uri="spotify:track:rt",
        artist_uri="spotify:artist:tj",
    )

    assert restored.history_id == original.history_id
    assert restored.account_id == original.account_id
    assert restored.song_uri == original.song_uri
    assert restored.outcome == original.outcome
    assert restored.proxy_ip_hash == "hash-abc"
    assert restored.proxy_country == "PE"


def test_session_record_round_trip_persisted_fields() -> None:
    started = datetime(2026, 4, 27, 18, 0, tzinfo=UTC)
    original = SessionRecord.new(account_id="acc-1", started_at=started)
    original.ended_at = started.replace(hour=19)
    original.target_streams_attempted = 4
    original.camouflage_streams_attempted = 6
    original.completed_normally = True
    original.add_event(
        BehaviorEvent.new(
            session_id=original.session_id,
            type=BehaviorType.PAUSE_RESUME,
            occurred_at=started.replace(minute=15),
        ),
    )

    model = from_domain_session_record(original)
    restored = to_domain_session_record(model)

    assert restored.session_id == original.session_id
    assert restored.target_streams_attempted == 4
    assert restored.camouflage_streams_attempted == 6
    assert restored.completed_normally is True
    assert len(restored.behavior_events) == 1
    assert restored.behavior_events[0].type == BehaviorType.PAUSE_RESUME
