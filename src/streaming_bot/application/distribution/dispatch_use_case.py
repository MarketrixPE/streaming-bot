"""Caso de uso central: distribuir un track a >=N distribuidores en paralelo.

Flujo:
1. Validar que la policy se puede satisfacer (al menos `min_distributors`
   adapters disponibles, ninguno excluido por la policy).
2. Seleccionar la lista final de distribuidores respetando `max_concentration_pct`
   sobre el total actual del catalogo (consultado a `IReleaseRepository`).
3. Resolver alias artist-name distinto por distribuidor (via `AliasResolver`).
4. Construir `Release` por distribuidor con el alias y los metadatos del track.
5. Delegar el envio paralelo al `DispatcherRouter` (o a un protocolo equivalente).
6. Persistir cada release y submission resultante.
7. Devolver `DispatchResult` con succeeded[] / failed[].

Errores reintentables (`DistributorTransientError`) NO se capturan aqui: el
caller (Temporal Workflow / scheduler) aplica la politica de retry. Errores
permanentes (`DistributorAPIError`) se reportan en el `DispatchResult` para
no romper el envio a los distros que SI funcionaron.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from streaming_bot.application.distribution.alias_resolver import AliasResolver
from streaming_bot.application.distribution.policy import DispatchPolicy
from streaming_bot.domain.distribution.distributor_id import (
    DistributorId,
    distributor_economics,
)
from streaming_bot.domain.distribution.release import (
    Release,
    ReleaseSubmission,
    TrackRef,
)
from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.ports.distributor_dispatcher import (
    DistributorAPIError,
    IReleaseRepository,
)

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger


class InsufficientDistributorsError(DomainError):
    """No hay suficientes distribuidores cableados para satisfacer la policy."""


class ConcentrationCapExceededError(DomainError):
    """Todos los distribuidores candidatos ya superan el cap de concentracion."""


@dataclass(frozen=True, slots=True)
class DispatchTrackRequest:
    """DTO de entrada al use case.

    Define lo minimo que el dispatcher necesita para enviar un track a
    cualquier distribuidor sin acoplarse al modelo `Song` del catalogo
    (que tiene muchos campos de boost irrelevantes para el dispatch).
    """

    track_id: str
    title: str
    audio_path: Path
    release_date: date
    isrc: str | None = None
    duration_seconds: int | None = None
    explicit: bool = False


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    """Resultado de envio para UN distribuidor."""

    distributor: DistributorId
    success: bool
    release: Release
    submission: ReleaseSubmission | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """Resultado agregado del envio multi-distribuidor."""

    track_id: str
    succeeded: tuple[DispatchOutcome, ...]
    failed: tuple[DispatchOutcome, ...] = ()
    skipped_distributors: tuple[DistributorId, ...] = field(default_factory=tuple)

    @property
    def total_attempted(self) -> int:
        return len(self.succeeded) + len(self.failed)

    @property
    def all_failed(self) -> bool:
        return not self.succeeded and bool(self.failed)


@runtime_checkable
class IDispatcherRouter(Protocol):
    """Contrato del router que ejecuta envios paralelos por distribuidor.

    Se define como Protocol para que el use case pueda recibir tanto el
    `DispatcherRouter` concreto de `infrastructure.distributors` como un fake
    en tests sin requerir herencia.
    """

    @property
    def available_distributors(self) -> frozenset[DistributorId]: ...

    async def dispatch(
        self,
        releases_by_distributor: dict[DistributorId, Release],
    ) -> dict[DistributorId, ReleaseSubmission | Exception]: ...


class MultiDistributorDispatchUseCase:
    """Orquesta el envio de UN track a >=N distros con aliases distintos."""

    def __init__(
        self,
        *,
        alias_resolver: AliasResolver,
        dispatcher_router: IDispatcherRouter,
        releases_repo: IReleaseRepository,
        logger: BoundLogger,
    ) -> None:
        self._alias_resolver = alias_resolver
        self._router = dispatcher_router
        self._releases_repo = releases_repo
        self._log = logger

    async def execute(
        self,
        request: DispatchTrackRequest,
        policy: DispatchPolicy,
    ) -> DispatchResult:
        log = self._log.bind(track_id=request.track_id)
        candidates = self._candidate_distributors(policy)
        if len(candidates) < policy.min_distributors:
            raise InsufficientDistributorsError(
                f"policy requiere {policy.min_distributors} distribuidores pero "
                f"hay {len(candidates)} cableados (excluyendo blocked)",
            )

        current_counts, total = await self._catalog_state()
        chosen, skipped = self._select_within_concentration_cap(
            candidates,
            current_counts=current_counts,
            total_releases=total,
            policy=policy,
        )
        if len(chosen) < policy.min_distributors:
            raise ConcentrationCapExceededError(
                "no hay suficientes distros bajo el cap de concentracion: "
                f"chosen={[d.value for d in chosen]} skipped={[d.value for d in skipped]}",
            )

        releases_by_distributor = await self._build_releases(request, chosen, policy)
        log.info(
            "dispatch.start",
            distributors=[d.value for d in chosen],
            skipped=[d.value for d in skipped],
        )

        submissions = await self._router.dispatch(releases_by_distributor)
        succeeded, failed = await self._persist_outcomes(
            releases_by_distributor=releases_by_distributor,
            submissions=submissions,
        )

        log.info(
            "dispatch.completed",
            succeeded=[o.distributor.value for o in succeeded],
            failed=[o.distributor.value for o in failed],
        )
        return DispatchResult(
            track_id=request.track_id,
            succeeded=tuple(succeeded),
            failed=tuple(failed),
            skipped_distributors=tuple(skipped),
        )

    def _candidate_distributors(self, policy: DispatchPolicy) -> list[DistributorId]:
        available = self._router.available_distributors
        return sorted(
            (d for d in available if d not in policy.excluded_distributors),
            key=lambda d: distributor_economics(d).annual_fee_per_track_usd,
        )

    async def _catalog_state(self) -> tuple[dict[DistributorId, int], int]:
        counts = await self._releases_repo.count_by_distributor()
        total = await self._releases_repo.total_releases()
        return counts, total

    def _select_within_concentration_cap(
        self,
        candidates: list[DistributorId],
        *,
        current_counts: dict[DistributorId, int],
        total_releases: int,
        policy: DispatchPolicy,
    ) -> tuple[list[DistributorId], list[DistributorId]]:
        """Selecciona distros que NO superarian el cap si reciben +1 release."""
        # Tras este envio el catalogo crecera en len(chosen). Estimamos con la
        # cota superior: total + len(candidates). Si un distro al recibir +1
        # quedaria por debajo del cap, lo aceptamos.
        projected_total = max(total_releases + len(candidates), 1)
        cap_per_distributor = max(int(projected_total * policy.max_concentration_pct), 1)

        chosen: list[DistributorId] = []
        skipped: list[DistributorId] = []
        for distributor in candidates:
            projected_count = current_counts.get(distributor, 0) + 1
            if projected_count <= cap_per_distributor:
                chosen.append(distributor)
            else:
                skipped.append(distributor)
        return chosen, skipped

    async def _build_releases(
        self,
        request: DispatchTrackRequest,
        distributors: list[DistributorId],
        policy: DispatchPolicy,
    ) -> dict[DistributorId, Release]:
        # Resolvemos aliases en paralelo (una I/O round-trip por distro al repo).
        resolved = await asyncio.gather(
            *[
                self._alias_resolver.resolve(track_id=request.track_id, distributor=d)
                for d in distributors
            ]
        )
        releases: dict[DistributorId, Release] = {}
        for distributor, resolved_alias in zip(distributors, resolved, strict=True):
            track = TrackRef(
                track_id=request.track_id,
                title=request.title,
                artist_name=resolved_alias.alias.alias_name,
                audio_path=request.audio_path,
                isrc=request.isrc,
                duration_seconds=request.duration_seconds,
                explicit=request.explicit,
            )
            releases[distributor] = Release.new(
                tracks=(track,),
                artist_name=resolved_alias.alias.alias_name,
                label_name=policy.label_name,
                distributor=distributor,
                release_date=request.release_date,
                isrc=request.isrc,
            )
        return releases

    async def _persist_outcomes(
        self,
        *,
        releases_by_distributor: dict[DistributorId, Release],
        submissions: dict[DistributorId, ReleaseSubmission | Exception],
    ) -> tuple[list[DispatchOutcome], list[DispatchOutcome]]:
        succeeded: list[DispatchOutcome] = []
        failed: list[DispatchOutcome] = []
        for distributor, release in releases_by_distributor.items():
            outcome = submissions.get(distributor)
            if isinstance(outcome, ReleaseSubmission):
                await self._releases_repo.save(release)
                await self._releases_repo.save_submission(outcome)
                succeeded.append(
                    DispatchOutcome(
                        distributor=distributor,
                        success=True,
                        release=release,
                        submission=outcome,
                    )
                )
                continue

            error_message = self._format_error(outcome)
            self._log.warning(
                "dispatch.distributor_failed",
                distributor=distributor.value,
                error=error_message,
            )
            failed.append(
                DispatchOutcome(
                    distributor=distributor,
                    success=False,
                    release=release,
                    error_message=error_message,
                )
            )
        return succeeded, failed

    @staticmethod
    def _format_error(outcome: ReleaseSubmission | Exception | None) -> str:
        if isinstance(outcome, DistributorAPIError):
            return f"api_error:{outcome}"
        if isinstance(outcome, Exception):
            return f"unexpected:{outcome}"
        return "missing_outcome"
