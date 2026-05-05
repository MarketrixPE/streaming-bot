"""Metricas Prometheus para SLO/alerting.

Implementa el puerto IObservabilityMetrics (application/ports/metrics.py)
exponiendo metodos imperativos sencillos:
- record_stream(country, success, duration)
- increment_account_blocked()
- increment_proxy_failure()
- session_started() / session_ended()

Antes solo existia record_stream y los counters se mutaban "a mano" por
quien tuviera referencia. Ahora todos los call-sites usan la misma API
sin importar prometheus_client directamente, y los tests pueden inyectar
NullMetrics.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server


class Metrics:
    """Registro central de metricas. Singleton-friendly via DI."""

    def __init__(self) -> None:
        self.stream_attempts_total = Counter(
            "streaming_bot_stream_attempts_total",
            "Intentos totales de stream",
            labelnames=("country", "result"),
        )
        self.stream_duration_seconds = Histogram(
            "streaming_bot_stream_duration_seconds",
            "Duracion de un stream completo",
            labelnames=("country", "result"),
            buckets=(1, 5, 10, 30, 60, 120, 300, 600),
        )
        self.accounts_blocked_total = Counter(
            "streaming_bot_accounts_blocked_total",
            "Cuentas marcadas como bloqueadas",
        )
        self.proxies_failed_total = Counter(
            "streaming_bot_proxies_failed_total",
            "Proxies que fallaron health-check",
        )
        self.active_sessions = Gauge(
            "streaming_bot_active_sessions",
            "Sesiones de browser actualmente abiertas",
        )

    def record_stream(
        self,
        *,
        country: str,
        success: bool,
        duration_seconds: float,
    ) -> None:
        result = "success" if success else "failure"
        self.stream_attempts_total.labels(country=country, result=result).inc()
        self.stream_duration_seconds.labels(country=country, result=result).observe(
            duration_seconds,
        )

    def increment_account_blocked(self) -> None:
        self.accounts_blocked_total.inc()

    def increment_proxy_failure(self) -> None:
        self.proxies_failed_total.inc()

    def session_started(self) -> None:
        self.active_sessions.inc()

    def session_ended(self) -> None:
        self.active_sessions.dec()


def start_metrics_server(port: int = 9090) -> None:
    """Levanta el endpoint /metrics de Prometheus en un thread separado."""
    start_http_server(port)
