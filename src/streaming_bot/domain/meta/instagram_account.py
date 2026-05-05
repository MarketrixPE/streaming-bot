"""``InstagramAccount``: cuenta de Instagram asociada 1:1 a un artista del catalogo.

Mapping sticky persona-artista-cuenta_IG: cada artista tiene exactamente una
cuenta IG asignada. La cuenta nunca se reutiliza para otro artista (la huella
de un artista no contamina a otro).

El ``device_fingerprint`` se persiste y reusa entre sesiones para minimizar
los ``challenge_required`` de instagrapi (cambios de device disparan auth
extra). En v1 se serializa como ``dict[str, str]`` plano para simplicidad.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4


class InstagramAccountStatus(str, Enum):
    """Estado operativo de la cuenta IG.

    - ``WARMING``: recien creada, hace solo navegacion organica (no posts target).
    - ``ACTIVE``: lista para postear Reels y compartir smart-links.
    - ``CHALLENGE``: instagrapi reporto ``challenge_required``; pendiente
      resolucion via Patchright fallback (o intervencion humana).
    - ``BANNED``: cuenta deshabilitada por Meta. No se reasigna a otro artista.
    """

    WARMING = "warming"
    ACTIVE = "active"
    CHALLENGE = "challenge"
    BANNED = "banned"


@dataclass(slots=True)
class InstagramAccount:
    """Cuenta IG persistente vinculada a un artista del catalogo.

    Invariantes:
    - ``username`` unico en el sistema (asignacion sticky).
    - ``artist_uri`` apunta a un artista del catalogo (``catalog:artist:...``
      o ``spotify:artist:...``); el provisioning service garantiza 1:1.
    - ``device_fingerprint`` debe reusarse en cada sesion para no disparar
      challenge.
    """

    id: str
    username: str
    persona_id: str
    artist_uri: str
    device_fingerprint: dict[str, str] = field(default_factory=dict)
    status: InstagramAccountStatus = InstagramAccountStatus.WARMING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_login_at: datetime | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.username:
            raise ValueError("InstagramAccount.username no puede estar vacio")
        if not self.persona_id:
            raise ValueError("InstagramAccount.persona_id no puede estar vacio")
        if not self.artist_uri:
            raise ValueError("InstagramAccount.artist_uri no puede estar vacio")

    @classmethod
    def new(
        cls,
        *,
        username: str,
        persona_id: str,
        artist_uri: str,
        device_fingerprint: dict[str, str] | None = None,
    ) -> InstagramAccount:
        """Constructor canonico. Nuevas cuentas arrancan en WARMING."""
        return cls(
            id=str(uuid4()),
            username=username,
            persona_id=persona_id,
            artist_uri=artist_uri,
            device_fingerprint=dict(device_fingerprint or {}),
            status=InstagramAccountStatus.WARMING,
        )

    @property
    def is_postable(self) -> bool:
        """Solo cuentas ACTIVE pueden postear Reels target."""
        return self.status is InstagramAccountStatus.ACTIVE

    def mark_active(self) -> None:
        """Promueve la cuenta a ACTIVE tras completar warming."""
        self.status = InstagramAccountStatus.ACTIVE
        self.updated_at = datetime.now(UTC)

    def mark_challenge(self, reason: str) -> None:
        """instagrapi devolvio challenge_required: pasa a CHALLENGE."""
        self.status = InstagramAccountStatus.CHALLENGE
        self.notes = f"challenge:{reason}"
        self.updated_at = datetime.now(UTC)

    def mark_banned(self, reason: str) -> None:
        """Marca BANNED y queda fuera del pool. No se reasigna a otro artista."""
        self.status = InstagramAccountStatus.BANNED
        self.notes = f"banned:{reason}"
        self.updated_at = datetime.now(UTC)

    def record_login(self) -> None:
        """Registra que el cliente abrio sesion exitosamente."""
        self.last_login_at = datetime.now(UTC)
        self.updated_at = self.last_login_at
