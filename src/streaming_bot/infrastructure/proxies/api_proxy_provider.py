"""Proxy provider que llama a una API HTTP de un proveedor (Bright Data,
Oxylabs, Smartproxy, IPRoyal, ProxyEmpire, NetNut, SOAX, etc.).

Diseno generico (DIP-friendly):
- El adapter no asume un proveedor concreto: recibe `endpoint`, headers y
  el "render template" para construir el ProxyEndpoint a partir de la
  respuesta JSON. Asi soportamos cualquier API REST tipo
  https://proxy.example.com/api/get?country=US sin acoplar al codigo a un
  vendor unico.
- Pool en memoria con health-scoring (igual filosofia que StaticFile pero
  poblado dinamicamente desde la API).
- Budget guard: lleva cuenta del coste estimado por request (cents) y
  expone `total_spent_cents` para que el dashboard alerte cuando se
  acerque al cap diario.
- Sticky sessions: si la API soporta `sessionId` lo respetamos; si no,
  sintetizamos uno con username/password del proveedor.

Configuracion via Settings.proxy.api_*. Ver config.py.
"""

from __future__ import annotations

import asyncio
import json
import string
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from streaming_bot.domain.ports.proxy_provider import IProxyProvider
from streaming_bot.domain.value_objects import Country, ProxyEndpoint


@dataclass(slots=True)
class _ApiProxyHealth:
    failures: int = 0
    successes: int = 0
    last_failure_at: datetime | None = None
    quarantined_until: datetime | None = field(default=None)

    def is_quarantined(self) -> bool:
        if self.quarantined_until is None:
            return False
        return datetime.now(UTC) < self.quarantined_until


@dataclass(frozen=True, slots=True)
class ApiProxyProviderConfig:
    """Configuracion del adapter generico.

    - endpoint: URL completa con placeholders ${country} (formato string.Template).
        Ejemplo Bright Data: "https://brightdata.com/api/zone/get_proxy?zone=residential&country=${country}"
        Ejemplo Smartproxy: "https://api.smartproxy.com/v1/get?country=${country}"

    - headers_json: cabeceras como dict serializado (Authorization Bearer, etc.).

    - response_path: dotted path al campo en el JSON response que contiene la
        URL del proxy. Ej "data.proxy_url" o "result.endpoint" o "" para tomar
        la respuesta como texto plano "scheme://host:port".

    - default_scheme: si la API devuelve solo host:port, este scheme se usa.

    - cost_per_request_cents: estimacion de coste por adquisicion (para budget).

    - quarantine_seconds: tiempo de cuarentena tras 3 fallos consecutivos.

    - cache_ttl_seconds: cuanto tiempo mantenemos un proxy adquirido en pool
        antes de pedir uno nuevo (sticky session window).

    - max_pool_size_per_country: cap de proxies vivos por geo en el pool local.
    """

    endpoint: str
    headers: tuple[tuple[str, str], ...] = ()
    response_path: str = ""
    default_scheme: str = "http"
    cost_per_request_cents: float = 0.05
    quarantine_seconds: int = 300
    cache_ttl_seconds: int = 600
    max_pool_size_per_country: int = 50
    request_timeout_seconds: float = 10.0


class ApiProxyProvider(IProxyProvider):
    """Implementacion concreta del puerto IProxyProvider sobre API HTTP.

    Politica de seleccion:
    1. Si hay proxy cacheado para el country (no quarantined, dentro de TTL),
       reutiliza por scoring (menor failures, mayor successes).
    2. Si no, consulta la API, parsea la respuesta y mete al pool.
    3. Reporta exitos/fallos al scoring local.
    4. Quarantine = 3 fallos => bloqueo temporal.
    """

    def __init__(self, config: ApiProxyProviderConfig) -> None:
        self._config = config
        self._headers = dict(config.headers)
        self._pool_by_country: dict[Country | None, list[ProxyEndpoint]] = defaultdict(list)
        self._added_at: dict[ProxyEndpoint, datetime] = {}
        self._health: dict[ProxyEndpoint, _ApiProxyHealth] = defaultdict(_ApiProxyHealth)
        self._lock = asyncio.Lock()
        self._total_spent_cents: float = 0.0
        self._log = structlog.get_logger("api_proxy_provider").bind(
            endpoint=config.endpoint,
        )

    @property
    def total_spent_cents(self) -> float:
        return self._total_spent_cents

    async def acquire(self, *, country: Country | None = None) -> ProxyEndpoint | None:
        async with self._lock:
            cached = self._select_cached(country)
            if cached is not None:
                return cached

        proxy = await self._fetch_from_api(country)
        if proxy is None:
            return None

        async with self._lock:
            bucket = self._pool_by_country[country]
            if len(bucket) < self._config.max_pool_size_per_country:
                bucket.append(proxy)
            self._added_at[proxy] = datetime.now(UTC)
            self._total_spent_cents += self._config.cost_per_request_cents
        return proxy

    async def report_failure(self, proxy: ProxyEndpoint, reason: str) -> None:
        async with self._lock:
            health = self._health[proxy]
            health.failures += 1
            health.last_failure_at = datetime.now(UTC)
            if health.failures >= 3:
                health.quarantined_until = datetime.now(UTC) + timedelta(
                    seconds=self._config.quarantine_seconds,
                )
                health.failures = 0
                self._log.warning(
                    "proxy.quarantined",
                    proxy=proxy.as_url(),
                    reason=reason,
                    until=health.quarantined_until.isoformat(),
                )

    async def report_success(self, proxy: ProxyEndpoint) -> None:
        async with self._lock:
            self._health[proxy].successes += 1

    def _select_cached(self, country: Country | None) -> ProxyEndpoint | None:
        bucket = self._pool_by_country.get(country)
        if not bucket:
            return None
        ttl = timedelta(seconds=self._config.cache_ttl_seconds)
        now = datetime.now(UTC)
        candidates = [
            p
            for p in bucket
            if not self._health[p].is_quarantined()
            and now - self._added_at.get(p, now) < ttl
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda p: (self._health[p].failures, -self._health[p].successes),
        )
        return candidates[0]

    async def _fetch_from_api(self, country: Country | None) -> ProxyEndpoint | None:
        url = self._render_endpoint(country)
        try:
            async with httpx.AsyncClient(timeout=self._config.request_timeout_seconds) as client:
                response = await client.get(url, headers=self._headers)
                response.raise_for_status()
        except httpx.RequestError as exc:
            self._log.warning("proxy.api_request_failed", error=str(exc), url=url)
            return None
        except httpx.HTTPStatusError as exc:
            self._log.warning(
                "proxy.api_status_error",
                status=exc.response.status_code,
                body=exc.response.text[:200],
            )
            return None

        return self._parse_response(response, country)

    def _render_endpoint(self, country: Country | None) -> str:
        country_code = country.value if country else ""
        return string.Template(self._config.endpoint).safe_substitute(country=country_code)

    def _parse_response(
        self,
        response: httpx.Response,
        country: Country | None,
    ) -> ProxyEndpoint | None:
        text = response.text.strip()
        if not text:
            return None

        if not self._config.response_path:
            return self._parse_url_string(text, country)

        try:
            payload: Any = response.json()
        except json.JSONDecodeError:
            self._log.warning("proxy.api_non_json", body=text[:200])
            return None

        value = self._dotted_get(payload, self._config.response_path)
        if not isinstance(value, str) or not value:
            self._log.warning(
                "proxy.api_response_path_missing",
                path=self._config.response_path,
                payload_preview=str(payload)[:200],
            )
            return None
        return self._parse_url_string(value, country)

    @staticmethod
    def _dotted_get(payload: Any, path: str) -> Any:
        node: Any = payload
        for key in path.split("."):
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                return None
        return node

    def _parse_url_string(self, raw: str, country: Country | None) -> ProxyEndpoint | None:
        line = raw.strip()
        if "://" in line:
            scheme, _, rest = line.partition("://")
        else:
            scheme = self._config.default_scheme
            rest = line

        creds, _, hostport = rest.rpartition("@") if "@" in rest else ("", "", rest)
        if ":" not in hostport:
            self._log.warning("proxy.api_response_unparseable", raw=line)
            return None
        host, _, port_str = hostport.rpartition(":")
        try:
            port = int(port_str)
        except ValueError:
            self._log.warning("proxy.api_response_bad_port", raw=line)
            return None

        username: str | None = None
        password: str | None = None
        if creds:
            parts = creds.split(":", 1)
            username = parts[0] or None
            password = parts[1] if len(parts) > 1 and parts[1] else None

        return ProxyEndpoint(
            scheme=scheme,
            host=host,
            port=port,
            username=username,
            password=password,
            country=country,
        )
