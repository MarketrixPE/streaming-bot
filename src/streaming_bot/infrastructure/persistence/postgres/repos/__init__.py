"""Repositorios concretos que implementan los puertos de dominio."""

from streaming_bot.infrastructure.persistence.postgres.repos.account_repository import (
    PostgresAccountRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.artist_repository import (
    PostgresArtistRepository,
)
from streaming_bot.infrastructure.persistence.postgres.repos.experiment_repository import (
    PostgresExperimentRepository,
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
from streaming_bot.infrastructure.persistence.postgres.repos.persona_memory_repository import (
    PostgresPersonaMemoryRepository,
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
from streaming_bot.infrastructure.persistence.postgres.repos.variant_assignment_repository import (
    PostgresVariantAssignmentRepository,
)

__all__ = [
    "PostgresAccountRepository",
    "PostgresArtistRepository",
    "PostgresExperimentRepository",
    "PostgresLabelRepository",
    "PostgresModemRepository",
    "PostgresPersonaMemoryRepository",
    "PostgresPersonaRepository",
    "PostgresPlaylistRepository",
    "PostgresSessionRecordRepository",
    "PostgresSongRepository",
    "PostgresStreamHistoryRepository",
    "PostgresVariantAssignmentRepository",
]
