"""Mappers puros entre entidades de dominio y modelos ORM.

Reglas:
- Sin I/O (no se hacen queries aquí).
- Funciones, no clases (la traducción es transformación, no servicio).
- Pares simétricos `to_domain_X` / `from_domain_X` para enforcement de
  round-trip en tests.

Limitación documentada: algunos campos del dominio no tienen columna
explícita en el esquema (ver `to_domain_session_record`). Se reconstruyen
con valores neutros conscientes para no propagar `None` ambiguos.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import cast

from streaming_bot.domain.artist import Artist, ArtistStatus
from streaming_bot.domain.entities import Account, AccountStatus
from streaming_bot.domain.history import (
    BehaviorEvent,
    BehaviorType,
    SessionRecord,
    StreamHistory,
    StreamOutcome,
)
from streaming_bot.domain.label import DistributorType, Label, LabelHealth
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
from streaming_bot.domain.song import Distributor, Song, SongMetadata, SongRole, SongTier
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.persistence.postgres.models.account import AccountModel
from streaming_bot.infrastructure.persistence.postgres.models.artist import ArtistModel
from streaming_bot.infrastructure.persistence.postgres.models.history import (
    SessionRecordModel,
    StreamHistoryModel,
)
from streaming_bot.infrastructure.persistence.postgres.models.label import LabelModel
from streaming_bot.infrastructure.persistence.postgres.models.modem import ModemModel
from streaming_bot.infrastructure.persistence.postgres.models.persona import (
    PersonaMemorySnapshotModel,
    PersonaModel,
)
from streaming_bot.infrastructure.persistence.postgres.models.playlist import (
    PlaylistModel,
    PlaylistTrackModel,
)
from streaming_bot.infrastructure.persistence.postgres.models.song import SongModel

# --------------------------------------------------------------------------- #
# Account
# --------------------------------------------------------------------------- #


def from_domain_account(account: Account) -> AccountModel:
    """Domain -> ORM. La contraseña debe venir ya cifrada."""
    return AccountModel(
        id=account.id,
        username=account.username,
        password_encrypted=account.password,
        country=account.country.value,
        state=account.status.state,
        reason=account.status.reason,
        last_used_at=account.last_used_at,
    )


def apply_account_to_model(account: Account, model: AccountModel) -> None:
    """Aplica los cambios del dominio sobre un modelo ya cargado en sesión.

    Útil en `update`: evita reemplazar el row completo y permite que
    SQLAlchemy emita solo los campos modificados.
    """
    model.username = account.username
    model.password_encrypted = account.password
    model.country = account.country.value
    model.state = account.status.state
    model.reason = account.status.reason
    model.last_used_at = account.last_used_at


def to_domain_account(model: AccountModel) -> Account:
    """ORM -> Domain. Reconstruye `AccountStatus` desde state+reason."""
    if model.state == "banned":
        status = AccountStatus.banned(model.reason or "")
    elif model.state == "rate_limited":
        status = AccountStatus.rate_limited(model.reason or "")
    else:
        status = AccountStatus.active()
    return Account(
        id=model.id,
        username=model.username,
        password=model.password_encrypted,
        country=Country(model.country),
        status=status,
        last_used_at=model.last_used_at,
    )


# --------------------------------------------------------------------------- #
# Song
# --------------------------------------------------------------------------- #


def from_domain_song(song: Song, *, model_id: str | None = None) -> SongModel:
    """Domain -> ORM. `model_id` permite preservar el ULID en updates."""
    distribution_serialized: dict[str, float] = {
        country.value: weight for country, weight in song.top_country_distribution.items()
    }
    kwargs: dict[str, object] = {
        "spotify_uri": song.spotify_uri,
        "isrc": song.metadata.isrc,
        "title": song.title,
        "artist_name": song.artist_name,
        "artist_uri": song.artist_uri,
        "role": song.role.value,
        "distributor": song.distributor.value if song.distributor else None,
        "album_name": None,
        "duration_seconds": song.metadata.duration_seconds,
        "primary_artist_id": song.primary_artist_id,
        "featured_artist_ids": list(song.featured_artist_ids),
        "label_id": song.label_id,
        "baseline_streams_per_day": song.baseline_streams_per_day,
        "target_streams_per_day": song.target_streams_per_day,
        "safe_ceiling_today": song.safe_ceiling_today(),
        "current_streams_today": song.current_streams_today,
        "is_active": song.is_active,
        "tier": song.tier.value,
        "top_country_distribution": distribution_serialized,
        "spike_oct2025_flag": song.spike_oct2025_flag,
        "flag_notes": song.flag_notes,
    }
    if model_id is not None:
        kwargs["id"] = model_id
    return SongModel(**kwargs)


def apply_song_to_model(song: Song, model: SongModel) -> None:
    """Sobreescribe atributos de un SongModel con el estado del dominio."""
    model.spotify_uri = song.spotify_uri
    model.isrc = song.metadata.isrc
    model.title = song.title
    model.artist_name = song.artist_name
    model.artist_uri = song.artist_uri
    model.role = song.role.value
    model.distributor = song.distributor.value if song.distributor else None
    model.duration_seconds = song.metadata.duration_seconds
    model.primary_artist_id = song.primary_artist_id
    model.featured_artist_ids = list(song.featured_artist_ids)
    model.label_id = song.label_id
    model.baseline_streams_per_day = song.baseline_streams_per_day
    model.target_streams_per_day = song.target_streams_per_day
    model.safe_ceiling_today = song.safe_ceiling_today()
    model.current_streams_today = song.current_streams_today
    model.is_active = song.is_active
    model.tier = song.tier.value
    model.top_country_distribution = {
        country.value: weight for country, weight in song.top_country_distribution.items()
    }
    model.spike_oct2025_flag = song.spike_oct2025_flag
    model.flag_notes = song.flag_notes


def to_domain_song(model: SongModel) -> Song:
    """ORM -> Domain. Reconstruye `SongMetadata` con los campos persistidos."""
    distribution: dict[Country, float] = {
        Country(code): weight for code, weight in (model.top_country_distribution or {}).items()
    }
    metadata = SongMetadata(
        duration_seconds=model.duration_seconds,
        isrc=model.isrc,
    )
    return Song(
        spotify_uri=model.spotify_uri,
        title=model.title,
        artist_name=model.artist_name,
        artist_uri=model.artist_uri,
        role=SongRole(model.role),
        metadata=metadata,
        primary_artist_id=model.primary_artist_id,
        featured_artist_ids=tuple(model.featured_artist_ids or []),
        label_id=model.label_id,
        distributor=Distributor(model.distributor) if model.distributor else None,
        baseline_streams_per_day=model.baseline_streams_per_day,
        target_streams_per_day=model.target_streams_per_day,
        current_streams_today=model.current_streams_today,
        is_active=model.is_active,
        tier=SongTier(model.tier),
        spike_oct2025_flag=model.spike_oct2025_flag,
        flag_notes=model.flag_notes,
        top_country_distribution=distribution,
    )


# --------------------------------------------------------------------------- #
# Artist
# --------------------------------------------------------------------------- #


def from_domain_artist(artist: Artist) -> ArtistModel:
    """Domain -> ORM."""
    return ArtistModel(
        id=artist.id,
        name=artist.name,
        spotify_uri=artist.spotify_uri,
        aliases=list(artist.aliases),
        primary_country=(artist.primary_country.value if artist.primary_country else None),
        primary_genres=list(artist.primary_genres),
        label_id=artist.label_id,
        status=artist.status.value,
        has_spike_history=artist.has_spike_history,
        notes=artist.notes,
    )


def apply_artist_to_model(artist: Artist, model: ArtistModel) -> None:
    """Update parcial sobre un ArtistModel cargado en sesión."""
    model.name = artist.name
    model.spotify_uri = artist.spotify_uri
    model.aliases = list(artist.aliases)
    model.primary_country = artist.primary_country.value if artist.primary_country else None
    model.primary_genres = list(artist.primary_genres)
    model.label_id = artist.label_id
    model.status = artist.status.value
    model.has_spike_history = artist.has_spike_history
    model.notes = artist.notes


def to_domain_artist(model: ArtistModel) -> Artist:
    """ORM -> Domain."""
    return Artist(
        id=model.id,
        name=model.name,
        spotify_uri=model.spotify_uri,
        aliases=tuple(model.aliases or []),
        primary_country=Country(model.primary_country) if model.primary_country else None,
        primary_genres=tuple(model.primary_genres or []),
        label_id=model.label_id,
        status=ArtistStatus(model.status),
        has_spike_history=model.has_spike_history,
        notes=model.notes,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# --------------------------------------------------------------------------- #
# Label
# --------------------------------------------------------------------------- #


def from_domain_label(label: Label) -> LabelModel:
    """Domain -> ORM."""
    return LabelModel(
        id=label.id,
        name=label.name,
        distributor=label.distributor.value,
        distributor_account_id=label.distributor_account_id,
        owner_email=label.owner_email,
        health=label.health.value,
        last_health_check=label.last_health_check,
        notes=label.notes,
    )


def apply_label_to_model(label: Label, model: LabelModel) -> None:
    """Update parcial sobre un LabelModel."""
    model.name = label.name
    model.distributor = label.distributor.value
    model.distributor_account_id = label.distributor_account_id
    model.owner_email = label.owner_email
    model.health = label.health.value
    model.last_health_check = label.last_health_check
    model.notes = label.notes


def to_domain_label(model: LabelModel) -> Label:
    """ORM -> Domain."""
    return Label(
        id=model.id,
        name=model.name,
        distributor=DistributorType(model.distributor),
        distributor_account_id=model.distributor_account_id,
        owner_email=model.owner_email,
        health=LabelHealth(model.health),
        last_health_check=model.last_health_check,
        notes=model.notes,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# --------------------------------------------------------------------------- #
# Persona
# --------------------------------------------------------------------------- #


def _persona_traits_to_model_kwargs(traits: PersonaTraits) -> dict[str, object]:
    """Aplana traits a campos planos + JSON dicts."""
    return {
        "engagement_level": traits.engagement_level.value,
        "preferred_genres": list(traits.preferred_genres),
        "preferred_session_hour_start": traits.preferred_session_hour_local[0],
        "preferred_session_hour_end": traits.preferred_session_hour_local[1],
        "device": traits.device.value,
        "platform": traits.platform.value,
        "ui_language": traits.ui_language,
        "timezone": traits.timezone,
        "country": traits.country.value,
        "behaviors": asdict(traits.behaviors),
        "typing": asdict(traits.typing),
        "mouse": asdict(traits.mouse),
        "session_pattern": asdict(traits.session),
    }


def from_domain_persona(persona: Persona) -> PersonaModel:
    """Domain -> ORM. Solo crea la fila de traits (memoria va aparte)."""
    return PersonaModel(
        account_id=persona.account_id,
        created_at_iso=persona.created_at_iso,
        last_session_at_iso=persona.last_session_at_iso,
        **_persona_traits_to_model_kwargs(persona.traits),
    )


def memory_snapshot_from_domain(
    persona: Persona,
    *,
    snapshot_at: datetime,
) -> PersonaMemorySnapshotModel:
    """Crea un nuevo snapshot con el estado actual de `persona.memory`."""
    return PersonaMemorySnapshotModel(
        account_id=persona.account_id,
        liked_songs=sorted(persona.memory.liked_songs),
        saved_songs=sorted(persona.memory.saved_songs),
        followed_artists=sorted(persona.memory.followed_artists),
        followed_playlists=sorted(persona.memory.followed_playlists),
        own_playlists=list(persona.memory.own_playlists),
        recent_searches=list(persona.memory.recent_searches),
        recent_artists_visited=list(persona.memory.recent_artists_visited),
        total_stream_minutes=persona.memory.total_stream_minutes,
        total_streams=persona.memory.total_streams,
        snapshot_at=snapshot_at,
    )


def to_domain_persona(
    model: PersonaModel,
    snapshot: PersonaMemorySnapshotModel | None,
) -> Persona:
    """ORM -> Domain. Si no hay snapshot, devuelve memoria vacía."""
    traits = PersonaTraits(
        engagement_level=EngagementLevel(model.engagement_level),
        preferred_genres=tuple(model.preferred_genres or []),
        preferred_session_hour_local=(
            model.preferred_session_hour_start,
            model.preferred_session_hour_end,
        ),
        device=DeviceType(model.device),
        platform=PlatformProfile(model.platform),
        ui_language=model.ui_language,
        timezone=model.timezone,
        country=Country(model.country),
        behaviors=BehaviorProbabilities(**(model.behaviors or {})),
        typing=TypingProfile(**(model.typing or {})),
        mouse=MouseProfile(**(model.mouse or {})),
        session=SessionPattern(**(model.session_pattern or {})),
    )
    memory = _snapshot_to_memory(snapshot) if snapshot is not None else PersonaMemory()
    return Persona(
        account_id=model.account_id,
        traits=traits,
        memory=memory,
        created_at_iso=model.created_at_iso,
        last_session_at_iso=model.last_session_at_iso,
    )


def _snapshot_to_memory(snapshot: PersonaMemorySnapshotModel) -> PersonaMemory:
    """Convierte un snapshot persistido a `PersonaMemory` (sets vs lists)."""
    return PersonaMemory(
        liked_songs=set(snapshot.liked_songs or []),
        saved_songs=set(snapshot.saved_songs or []),
        followed_artists=set(snapshot.followed_artists or []),
        followed_playlists=set(snapshot.followed_playlists or []),
        own_playlists=list(snapshot.own_playlists or []),
        recent_searches=list(snapshot.recent_searches or []),
        recent_artists_visited=list(snapshot.recent_artists_visited or []),
        total_stream_minutes=snapshot.total_stream_minutes,
        total_streams=snapshot.total_streams,
    )


# --------------------------------------------------------------------------- #
# Playlist
# --------------------------------------------------------------------------- #


def from_domain_playlist(playlist: Playlist) -> PlaylistModel:
    """Domain -> ORM. Se crean también los tracks como filas relacionadas."""
    return PlaylistModel(
        id=playlist.id,
        spotify_id=playlist.spotify_id,
        name=playlist.name,
        kind=playlist.kind.value,
        visibility=playlist.visibility.value,
        owner_account_id=playlist.owner_account_id,
        territory=playlist.territory.value if playlist.territory else None,
        genre=playlist.genre,
        description=playlist.description,
        cover_image_path=playlist.cover_image_path,
        follower_count=playlist.follower_count,
        last_synced_at=playlist.last_synced_at,
        tracks=[from_domain_playlist_track(t) for t in playlist.tracks],
    )


def from_domain_playlist_track(track: PlaylistTrack) -> PlaylistTrackModel:
    """Domain -> ORM. ID se genera con ULID por defecto."""
    return PlaylistTrackModel(
        track_uri=track.track_uri,
        position=track.position,
        is_target=track.is_target,
        duration_ms=track.duration_ms,
        artist_uri=track.artist_uri,
        title=track.title,
    )


def to_domain_playlist(model: PlaylistModel) -> Playlist:
    """ORM -> Domain. Tracks ya vienen ordenados por `position`."""
    territory = Country(model.territory) if model.territory else None
    return Playlist(
        id=model.id,
        spotify_id=model.spotify_id,
        name=model.name,
        kind=PlaylistKind(model.kind),
        visibility=PlaylistVisibility(model.visibility),
        owner_account_id=model.owner_account_id,
        territory=territory,
        genre=model.genre,
        tracks=[to_domain_playlist_track(t) for t in model.tracks],
        description=model.description,
        cover_image_path=model.cover_image_path,
        follower_count=model.follower_count,
        last_synced_at=model.last_synced_at,
        created_at=model.created_at,
    )


def to_domain_playlist_track(model: PlaylistTrackModel) -> PlaylistTrack:
    """ORM -> Domain."""
    return PlaylistTrack(
        track_uri=model.track_uri,
        position=model.position,
        is_target=model.is_target,
        duration_ms=model.duration_ms,
        artist_uri=model.artist_uri,
        title=model.title,
    )


# --------------------------------------------------------------------------- #
# Modem
# --------------------------------------------------------------------------- #


def from_domain_modem(modem: Modem) -> ModemModel:
    """Domain -> ORM. ModemHardware se aplana en columnas."""
    return ModemModel(
        id=modem.id,
        imei=modem.hardware.imei,
        iccid=modem.hardware.iccid,
        model=modem.hardware.model,
        serial_port=modem.hardware.serial_port,
        operator=modem.hardware.operator,
        sim_country=modem.hardware.sim_country.value,
        state=modem.state.value,
        current_public_ip=modem.current_public_ip,
        last_rotation_at=modem.last_rotation_at,
        last_used_at=modem.last_used_at,
        last_health_check_at=modem.last_health_check_at,
        accounts_used_today=modem.accounts_used_today,
        streams_served_today=modem.streams_served_today,
        flagged_count=modem.flagged_count,
        notes=modem.notes,
        max_accounts_per_day=modem.max_accounts_per_day,
        max_streams_per_day=modem.max_streams_per_day,
        rotation_cooldown_seconds=modem.rotation_cooldown_seconds,
        use_cooldown_seconds=modem.use_cooldown_seconds,
    )


def apply_modem_to_model(modem: Modem, model: ModemModel) -> None:
    """Update parcial del modem (no se altera la PK ni el hardware fijo)."""
    model.state = modem.state.value
    model.current_public_ip = modem.current_public_ip
    model.last_rotation_at = modem.last_rotation_at
    model.last_used_at = modem.last_used_at
    model.last_health_check_at = modem.last_health_check_at
    model.accounts_used_today = modem.accounts_used_today
    model.streams_served_today = modem.streams_served_today
    model.flagged_count = modem.flagged_count
    model.notes = modem.notes
    model.max_accounts_per_day = modem.max_accounts_per_day
    model.max_streams_per_day = modem.max_streams_per_day
    model.rotation_cooldown_seconds = modem.rotation_cooldown_seconds
    model.use_cooldown_seconds = modem.use_cooldown_seconds


def to_domain_modem(model: ModemModel) -> Modem:
    """ORM -> Domain. Reconstruye `ModemHardware` (frozen)."""
    hardware = ModemHardware(
        imei=model.imei,
        iccid=model.iccid,
        model=model.model,
        serial_port=model.serial_port,
        operator=model.operator,
        sim_country=Country(model.sim_country),
    )
    return Modem(
        id=model.id,
        hardware=hardware,
        state=ModemState(model.state),
        current_public_ip=model.current_public_ip,
        last_rotation_at=model.last_rotation_at,
        last_used_at=model.last_used_at,
        last_health_check_at=model.last_health_check_at,
        accounts_used_today=model.accounts_used_today,
        streams_served_today=model.streams_served_today,
        flagged_count=model.flagged_count,
        notes=model.notes,
        created_at=model.created_at,
        max_accounts_per_day=model.max_accounts_per_day,
        max_streams_per_day=model.max_streams_per_day,
        rotation_cooldown_seconds=model.rotation_cooldown_seconds,
        use_cooldown_seconds=model.use_cooldown_seconds,
    )


# --------------------------------------------------------------------------- #
# Stream history
# --------------------------------------------------------------------------- #


def from_domain_stream_history(
    history: StreamHistory,
    *,
    song_id: str,
) -> StreamHistoryModel:
    """Domain -> ORM. Necesita el `song_id` interno (resuelto por el repo)."""
    return StreamHistoryModel(
        id=history.history_id,
        account_id=history.account_id,
        song_id=song_id,
        session_id=history.session_id,
        target_url=history.song_uri,
        listen_seconds=history.duration_listened_seconds,
        completed=history.outcome == StreamOutcome.COUNTED,
        outcome=history.outcome.value,
        error_message=history.error_class,
        started_at=history.occurred_at,
        completed_at=history.occurred_at if history.outcome != StreamOutcome.PENDING else None,
        country=history.proxy_country,
        proxy_used=history.proxy_ip_hash,
    )


def to_domain_stream_history(
    model: StreamHistoryModel,
    *,
    song_uri: str,
    artist_uri: str,
) -> StreamHistory:
    """ORM -> Domain. `song_uri`/`artist_uri` provienen del JOIN con songs."""
    return StreamHistory(
        history_id=model.id,
        account_id=model.account_id,
        song_uri=song_uri,
        artist_uri=artist_uri,
        occurred_at=model.started_at,
        duration_listened_seconds=model.listen_seconds,
        outcome=StreamOutcome(model.outcome),
        proxy_country=model.country,
        proxy_ip_hash=model.proxy_used,
        session_id=model.session_id,
        error_class=model.error_message,
    )


# --------------------------------------------------------------------------- #
# Session record
# --------------------------------------------------------------------------- #


def _behavior_event_to_dict(event: BehaviorEvent) -> dict[str, str | int]:
    """Serializa un evento para almacenarlo dentro del JSON `behaviors`."""
    return {
        "event_id": event.event_id,
        "session_id": event.session_id,
        "type": event.type.value,
        "occurred_at": event.occurred_at.isoformat(),
        "target_uri": event.target_uri or "",
        "duration_ms": event.duration_ms,
    }


def _behavior_event_from_dict(payload: dict[str, str | int]) -> BehaviorEvent:
    """Deserializa un evento desde JSON. Tipos coercionados explícitamente."""
    occurred_raw = cast(str, payload["occurred_at"])
    target_raw = cast(str, payload.get("target_uri", "")) or None
    return BehaviorEvent(
        event_id=cast(str, payload["event_id"]),
        session_id=cast(str, payload["session_id"]),
        type=BehaviorType(cast(str, payload["type"])),
        occurred_at=datetime.fromisoformat(occurred_raw),
        target_uri=target_raw,
        duration_ms=cast(int, payload.get("duration_ms", 0)),
    )


def from_domain_session_record(
    record: SessionRecord,
    *,
    persona_id: str | None = None,
    modem_id: str | None = None,
) -> SessionRecordModel:
    """Domain -> ORM. `total_streams` agrupa target+camuflaje atendidos."""
    total = record.target_streams_attempted + record.camouflage_streams_attempted
    duration_seconds = record.duration_seconds()
    outcome = "counted" if record.completed_normally else "failed"
    return SessionRecordModel(
        id=record.session_id,
        account_id=record.account_id,
        persona_id=persona_id,
        modem_id=modem_id,
        started_at=record.started_at,
        completed_at=record.ended_at,
        total_streams=total,
        target_streams=record.target_streams_attempted,
        duration_seconds=duration_seconds,
        outcome=outcome,
        error_message=record.error_class,
        behaviors=[_behavior_event_to_dict(e) for e in record.behavior_events],
    )


def to_domain_session_record(model: SessionRecordModel) -> SessionRecord:
    """ORM -> Domain. Reconstruye eventos y reparte target/camuflaje.

    Los siguientes campos del dominio NO se persisten (limitación aceptada):
    `proxy_country`, `proxy_ip_hash`, `user_agent`, `streams_counted`,
    `skips`, `likes_given`, `saves_given`, `follows_given`. Se reconstruyen
    con valores por defecto neutros para evitar nulos ambiguos.
    """
    behaviors_raw = cast(list[dict[str, str | int]], model.behaviors or [])
    events = [_behavior_event_from_dict(e) for e in behaviors_raw]
    target = model.target_streams
    camouflage = max(model.total_streams - target, 0)
    completed_at = model.completed_at
    if completed_at is None and model.duration_seconds > 0:
        completed_at = datetime.fromtimestamp(
            model.started_at.timestamp() + model.duration_seconds,
            tz=UTC,
        )
    return SessionRecord(
        session_id=model.id,
        account_id=model.account_id,
        started_at=model.started_at,
        ended_at=completed_at,
        target_streams_attempted=target,
        camouflage_streams_attempted=camouflage,
        behavior_events=events,
        error_class=model.error_message,
        completed_normally=model.outcome == "counted",
    )
