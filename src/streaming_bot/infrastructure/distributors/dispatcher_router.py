"""Router que ejecuta envios paralelos a varios `IDistributorDispatcher`.

Implementa el contrato `IDispatcherRouter` definido en application/distribution/
dispatch_use_case.py. Estrategia:

- Recibe en el constructor un mapping `{DistributorId: IDistributorDispatcher}`.
- En `dispatch(...)`, dispara `submit_release` por adapter usando
  `asyncio.gather(..., return_exceptions=True)`. De este modo un fallo en un
  distribuidor NO aborta los demas: el use case decide que hacer con cada
  outcome (succeed / fail / retry policy).
- Loggea per-distributor con structlog para trazabilidad.
"""

from __future__ import annotations

import asyncio

import structlog

from streaming_bot.domain.distribution.distributor_id import DistributorId
from streaming_bot.domain.distribution.release import Release, ReleaseSubmission
from streaming_bot.domain.ports.distributor_dispatcher import IDistributorDispatcher


class DispatcherRouter:
    """Orquestador paralelo de adapters por distribuidor."""

    def __init__(
        self,
        *,
        adapters: dict[DistributorId, IDistributorDispatcher],
    ) -> None:
        if not adapters:
            raise ValueError("DispatcherRouter requiere al menos un adapter cableado")
        for distributor, adapter in adapters.items():
            if adapter.distributor is not distributor:
                raise ValueError(
                    f"adapter.distributor={adapter.distributor.value} no coincide "
                    f"con la clave {distributor.value}",
                )
        self._adapters = adapters
        self._log = structlog.get_logger("dispatcher_router")

    @property
    def available_distributors(self) -> frozenset[DistributorId]:
        return frozenset(self._adapters.keys())

    async def dispatch(
        self,
        releases_by_distributor: dict[DistributorId, Release],
    ) -> dict[DistributorId, ReleaseSubmission | Exception]:
        unknown = set(releases_by_distributor) - set(self._adapters)
        if unknown:
            raise ValueError(
                f"distribuidores sin adapter cableado: {sorted(d.value for d in unknown)}",
            )
        if not releases_by_distributor:
            return {}

        ordered: list[tuple[DistributorId, Release]] = list(releases_by_distributor.items())
        coros = [
            self._submit_with_logging(distributor, release)
            for distributor, release in ordered
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)
        out: dict[DistributorId, ReleaseSubmission | Exception] = {}
        for (distributor, _), result in zip(ordered, results, strict=True):
            if isinstance(result, BaseException) and not isinstance(result, Exception):
                # Reraise verdaderas BaseException (KeyboardInterrupt, SystemExit):
                # nunca queremos enmascararlas como un fallo de un distribuidor.
                raise result
            out[distributor] = result
        return out

    async def _submit_with_logging(
        self,
        distributor: DistributorId,
        release: Release,
    ) -> ReleaseSubmission:
        adapter = self._adapters[distributor]
        log = self._log.bind(
            distributor=distributor.value,
            release_id=release.release_id,
            artist=release.artist_name,
        )
        log.info("router.submit.start")
        submission = await adapter.submit_release(release)
        log.info("router.submit.ok", submission_id=submission.submission_id)
        return submission
