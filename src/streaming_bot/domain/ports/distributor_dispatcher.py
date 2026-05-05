"""Puertos de distribucion multi-distribuidor.

Define las abstracciones que la capa application depende:
- `IDistributorDispatcher`: ingreso/takedown contra un distribuidor concreto.
- `IArtistAliasRepository`: persistencia track_id+distributor -> alias.
- `IReleaseRepository`: persistencia de releases para auditoria y para el
  calculo de concentracion del catalogo.

Las implementaciones viven en `infrastructure/distributors/*` (adapters HTTP
o browser scrape) y `infrastructure/repos/*` (SQLAlchemy).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from streaming_bot.domain.distribution.distributor_id import DistributorId
from streaming_bot.domain.distribution.release import (
    ArtistAlias,
    Release,
    ReleaseStatus,
    ReleaseSubmission,
)
from streaming_bot.domain.exceptions import PermanentError, TransientError


class DistributorAPIError(PermanentError):
    """Error permanente del distribuidor (selectores cambiados, 4xx).

    Se distingue de `DistributorTransientError` para que la politica de retry
    en application no reintente automaticamente algo que requiere intervencion
    humana (selector roto = ops debe redeplegar).
    """


class DistributorTransientError(TransientError):
    """Error reintentable del distribuidor (5xx, timeout, captcha temporal)."""


@runtime_checkable
class IDistributorDispatcher(Protocol):
    """Adapter de UN distribuidor concreto.

    Implementaciones: `DistroKidAdapter` (browser scrape via Patchright),
    `RouteNoteAdapter` (HTTP REST). Cada adapter es responsable de:
    - autenticar (cookies persistidas, login form, API key, etc.)
    - traducir el `Release` al payload nativo del distribuidor
    - reportar errores como `DistributorAPIError` o `DistributorTransientError`
    """

    @property
    def distributor(self) -> DistributorId: ...

    async def submit_release(self, release: Release) -> ReleaseSubmission:
        """Envia un release al distribuidor. Devuelve `ReleaseSubmission`.

        Raises:
            DistributorAPIError: si la API/UI rechaza permanentemente el envio
                (metadata invalida, selector inexistente, credenciales erroneas).
            DistributorTransientError: si hay un fallo reintentable.
        """
        ...

    async def get_status(self, submission_id: str) -> ReleaseStatus:
        """Consulta el estado actual de un release ya enviado."""
        ...

    async def request_takedown(self, submission_id: str) -> None:
        """Solicita el takedown de un release ya publicado."""
        ...


@runtime_checkable
class IArtistAliasRepository(Protocol):
    """Persistencia de aliases (track_id + distributor) -> alias_name.

    Garantiza idempotencia: el mismo track en el mismo distro siempre obtiene
    el mismo alias entre runs.
    """

    async def get(self, *, track_id: str, distributor: DistributorId) -> ArtistAlias | None: ...

    async def save(self, alias: ArtistAlias) -> None: ...

    async def list_for_track(self, track_id: str) -> list[ArtistAlias]: ...

    async def list_for_distributor(self, distributor: DistributorId) -> list[ArtistAlias]: ...


@runtime_checkable
class IReleaseRepository(Protocol):
    """Persistencia de releases enviados (auditoria + concentracion catalog)."""

    async def save(self, release: Release) -> None: ...

    async def save_submission(self, submission: ReleaseSubmission) -> None: ...

    async def count_by_distributor(self) -> dict[DistributorId, int]:
        """Devuelve {distribuidor: numero de releases vivos}.

        Usado por el dispatch use case para verificar el cap de concentracion
        antes de enviar nuevos releases.
        """
        ...

    async def total_releases(self) -> int: ...
