"""Sub-dominio SoundCloud: modelos, territorios monetizables y reglas Premier.

El paquete agrupa los value-objects y reglas de negocio especificas de
SoundCloud (programa Premier, fingerprinting de plays unicos, repost chains).
No contiene implementaciones de I/O ni adaptadores: la infra vive en
`infrastructure/soundcloud` y los casos de uso en `application/soundcloud`.
"""

from streaming_bot.domain.soundcloud.models import (
    PremierEligibility,
    RepostChain,
    SoundcloudTrack,
    SoundcloudUser,
)
from streaming_bot.domain.soundcloud.monetizable_territories import (
    MONETIZABLE_TERRITORIES,
    is_monetizable,
)

__all__ = [
    "MONETIZABLE_TERRITORIES",
    "PremierEligibility",
    "RepostChain",
    "SoundcloudTrack",
    "SoundcloudUser",
    "is_monetizable",
]
