"""Puerto de metricas operacionales para use cases.

Define un contrato minimo que los use cases pueden usar SIN depender de
prometheus_client (que vive en infrastructure/observability/metrics.py).
La capa infra implementa este protocol; los tests pueden inyectar un
NullMetrics o un MetricsSpy.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class IObservabilityMetrics(Protocol):
    """Metricas que reportan los casos de uso al pipeline de observabilidad."""

    def record_stream(
        self,
        *,
        country: str,
        success: bool,
        duration_seconds: float,
    ) -> None:
        """Registra el resultado de un intento de stream."""
        ...

    def increment_account_blocked(self) -> None:
        """Suma 1 al contador de cuentas marcadas como bloqueadas."""
        ...

    def increment_proxy_failure(self) -> None:
        """Suma 1 al contador de fallos de proxy reportados."""
        ...

    def session_started(self) -> None:
        """Marca apertura de una sesion de browser activa."""
        ...

    def session_ended(self) -> None:
        """Marca cierre de una sesion de browser."""
        ...


class NullMetrics:
    """Implementacion no-op para tests / dev sin Prometheus."""

    def record_stream(
        self,
        *,
        country: str,
        success: bool,
        duration_seconds: float,
    ) -> None:
        pass

    def increment_account_blocked(self) -> None:
        pass

    def increment_proxy_failure(self) -> None:
        pass

    def session_started(self) -> None:
        pass

    def session_ended(self) -> None:
        pass
