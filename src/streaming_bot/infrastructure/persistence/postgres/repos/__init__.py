"""Repositorios concretos que implementan los puertos de dominio."""

from streaming_bot.infrastructure.persistence.postgres.repos.account_repository import (
    PostgresAccountRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.artist_repository import (
    PostgresArtistRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.history_repository import (
    PostgresSessionRecordRepository,
    PostgresStreamHistoryRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.label_repository import (
    PostgresLabelRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.modem_repository import (
    PostgresModemRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.persona_repository import (
    PostgresPersonaRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.playlist_repository import (
    PostgresPlaylistRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.song_repository import (
    PostgresSongRepository,
)

__all__ = [
    "PostgresAccountRepository",
    "PostgresArtistRepository",
    "PostgresLabelRepository",
    "PostgresModemRepository",
    "PostgresPersonaRepository",
    "PostgresPlaylistRepository",
    "PostgresSessionRecordRepository",
    "PostgresSongRepository",
    "PostgresStreamHistoryRepository",
]
