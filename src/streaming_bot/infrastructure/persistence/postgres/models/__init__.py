"""Modelos ORM declarativos (SQLAlchemy 2.0 typed).

Importar todos los modelos aquí garantiza que `Base.metadata` queda completo
antes de que Alembic ejecute autogenerate o los tests llamen `create_all`.
"""

from streaming_bot.infrastructure.persistence.postgres.models.account import AccountModel
from streaming_bot.infrastructure.persistence.postgres.models.artist import ArtistModel
from streaming_bot.infrastructure.persistence.postgres.models.base import Base, TimestampMixin
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

__all__ = [
    "AccountModel",
    "ArtistModel",
    "Base",
    "LabelModel",
    "ModemModel",
    "PersonaMemorySnapshotModel",
    "PersonaModel",
    "PlaylistModel",
    "PlaylistTrackModel",
    "SessionRecordModel",
    "SongModel",
    "StreamHistoryModel",
    "TimestampMixin",
]
