"""Factory del Temporal Client.

Centralizamos la conexion para que cualquier capa (workers, schedulers,
job queue adapter) la obtenga via `TemporalClientFactory.get()` con TLS
opcional, namespace configurable y reintentos de conexion automaticos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from temporalio.client import Client


@dataclass(frozen=True, slots=True)
class TemporalClientConfig:
    host: str = "10.10.0.20:7233"
    namespace: str = "default"
    tls: bool = False
    api_key: str | None = None
    identity: str = "streaming-bot-control"


class TemporalClientFactory:
    """Crea (con cache) un Client Temporal."""

    def __init__(self, config: TemporalClientConfig) -> None:
        self._config = config
        self._client: Client | None = None

    async def get(self) -> Client:
        """Devuelve un Client conectado, instancia singleton."""
        if self._client is not None:
            return self._client
        try:
            from temporalio.client import Client
            from temporalio.service import TLSConfig
        except ImportError as exc:  # pragma: no cover - solo si extra no instalado
            raise RuntimeError(
                "temporalio no esta instalado. Anade `streaming-bot[temporal]` o "
                "`pip install temporalio` para usar la capa Temporal.",
            ) from exc

        tls: TLSConfig | bool = TLSConfig() if self._config.tls else False
        self._client = await Client.connect(
            self._config.host,
            namespace=self._config.namespace,
            tls=tls,
            api_key=self._config.api_key,
            identity=self._config.identity,
        )
        return self._client

    async def close(self) -> None:
        # Temporal Client no tiene close explicito en SDK 1.x: deja que el
        # GC libere. Mantenemos el metodo para simetria con context managers.
        self._client = None
