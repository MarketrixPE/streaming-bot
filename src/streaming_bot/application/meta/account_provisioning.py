"""``InstagramAccountProvisioningService``: 1 cuenta IG por artista del catalogo.

Asignacion sticky: cada ``Artist.spotify_uri`` (o ``catalog:artist:...``) tiene
exactamente UNA ``InstagramAccount``. El servicio idempotente: si ya existe
cuenta para el artista la devuelve, si no la crea via la factory inyectada.

Nota: la creacion fisica del account (signup IG completo) NO esta en este
servicio v1. La factory inyectada se asume previamente alimentada con
credenciales (instagrapi mobile API tiende a funcionar mejor con cuentas
creadas a mano + warming, no signup en bulk). v1 expone el contrato y queda
listo para que un creator real lo implemente.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

from streaming_bot.domain.meta.instagram_account import (
    InstagramAccount,
    InstagramAccountStatus,
)

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

    from streaming_bot.domain.artist import Artist


@runtime_checkable
class IInstagramAccountRepository(Protocol):
    """Repo dedicado para cuentas IG. Persiste el mapping sticky 1:1.

    Vive como Protocol local hasta que la infra de persistencia agregue su
    implementacion concreta (postgres). Aislar aqui evita acoplar otro
    sub-modulo del dominio mientras esta whitelist se mantiene chica.
    """

    async def get_by_artist_uri(self, artist_uri: str) -> InstagramAccount | None: ...

    async def get_by_username(self, username: str) -> InstagramAccount | None: ...

    async def add(self, account: InstagramAccount) -> None: ...

    async def update(self, account: InstagramAccount) -> None: ...

    async def list_active(self) -> list[InstagramAccount]: ...


class ProvisioningResult:
    """Outcome inmutable del provisioning de una cuenta para un artista."""

    __slots__ = ("account", "created")

    def __init__(self, *, account: InstagramAccount, created: bool) -> None:
        self.account = account
        self.created = created

    def __repr__(self) -> str:
        return f"ProvisioningResult(account={self.account.username!r}, created={self.created})"


# Factory async-friendly: dado un Artist, produce una nueva InstagramAccount.
# El fingerprint del device debe venir del seedeo o de la propia factory.
InstagramAccountFactory = Callable[["Artist"], "Awaitable[InstagramAccount]"]


class InstagramAccountProvisioningService:
    """Orquesta el mapping sticky persona-artista-cuenta_IG.

    Responsabilidades:
    - ``provision_for_artist``: idempotente. Si existe cuenta para el artista,
      la devuelve sin tocar; si no, llama a ``account_factory`` y persiste.
    - ``provision_for_catalog``: itera artistas activos y los provisiona en
      paralelo controlado.
    """

    def __init__(
        self,
        *,
        accounts: IInstagramAccountRepository,
        account_factory: InstagramAccountFactory,
        logger: BoundLogger | None = None,
    ) -> None:
        self._accounts = accounts
        self._factory = account_factory
        self._log: BoundLogger = logger or structlog.get_logger("meta.provisioning")

    async def provision_for_artist(self, artist: Artist) -> ProvisioningResult:
        """Devuelve la cuenta IG del artista, creandola si no existe."""
        artist_uri = self._artist_uri_for(artist)
        log = self._log.bind(artist_id=artist.id, artist_uri=artist_uri)

        existing = await self._accounts.get_by_artist_uri(artist_uri)
        if existing is not None:
            log.debug("provision.reused", username=existing.username, status=existing.status.value)
            return ProvisioningResult(account=existing, created=False)

        log.info("provision.creating")
        account = await self._factory(artist)

        if account.artist_uri != artist_uri:
            raise ValueError(
                f"factory devolvio cuenta con artist_uri inconsistente: "
                f"{account.artist_uri} vs {artist_uri}",
            )
        existing_username = await self._accounts.get_by_username(account.username)
        if existing_username is not None:
            raise ValueError(
                f"username '{account.username}' ya esta asignado a otro artista: "
                f"{existing_username.artist_uri}",
            )
        await self._accounts.add(account)
        log.info("provision.created", username=account.username)
        return ProvisioningResult(account=account, created=True)

    async def provision_for_catalog(
        self,
        artists: list[Artist],
    ) -> list[ProvisioningResult]:
        """Provisiona cuentas para una lista de artistas. Secuencial para
        no saturar el factory ni Meta (creacion en bulk dispara checkpoints).
        """
        results: list[ProvisioningResult] = []
        for artist in artists:
            result = await self.provision_for_artist(artist)
            results.append(result)
        return results

    async def list_postable_accounts(self) -> list[InstagramAccount]:
        """Cuentas listas para postear (status ACTIVE)."""
        all_active = await self._accounts.list_active()
        return [a for a in all_active if a.status is InstagramAccountStatus.ACTIVE]

    @staticmethod
    def _artist_uri_for(artist: Artist) -> str:
        """Resuelve URI canonico del artista. Prefiere ``spotify_uri``;
        si no, ``catalog:artist:<id>`` para artistas de catalogo AI.
        """
        if artist.spotify_uri:
            return artist.spotify_uri
        return f"catalog:artist:{artist.id}"
