"""Subdominio de distribucion multi-distribuidor.

Modela el ingreso de tracks a >=2 distribuidores distintos con artist-name
distinto por distro para resistir takedowns concentrados (caso Boomy 2023:
Spotify wipeo ~7% del catalogo cuando todos los uploads vivian en un solo
distribuidor con un mismo artist-name).
"""

from streaming_bot.domain.distribution.distributor_id import (
    DistributorEconomics,
    DistributorId,
    distributor_economics,
)
from streaming_bot.domain.distribution.release import (
    ArtistAlias,
    Release,
    ReleaseStatus,
    ReleaseSubmission,
    TrackRef,
)

__all__ = [
    "ArtistAlias",
    "DistributorEconomics",
    "DistributorId",
    "Release",
    "ReleaseStatus",
    "ReleaseSubmission",
    "TrackRef",
    "distributor_economics",
]
