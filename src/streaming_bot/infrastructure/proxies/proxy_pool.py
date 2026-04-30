"""Pool de proxies con health-check, rotación y scoring por país."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import httpx

from streaming_bot.domain.ports.proxy_provider import IProxyProvider
from streaming_bot.domain.value_objects import Country, ProxyEndpoint


class NoProxyProvider(IProxyProvider):
    """Modo direct: no usa proxies. Útil para desarrollo y tests."""

    async def acquire(self, *, country: Country | None = None) -> ProxyEndpoint | None:  # noqa: ARG002
        return None

    async def report_failure(self, proxy: ProxyEndpoint, reason: str) -> None:  # noqa: ARG002
        return None

    async def report_success(self, proxy: ProxyEndpoint) -> None:  # noqa: ARG002
        return None


@dataclass(slots=True)
class _ProxyHealth:
    failures: int = 0
    successes: int = 0
    last_failure_at: datetime | None = None
    quarantined_until: datetime | None = field(default=None)

    def is_quarantined(self) -> bool:
        if self.quarantined_until is None:
            return False
        return datetime.now(UTC) < self.quarantined_until


class StaticFileProxyProvider(IProxyProvider):
    """Lee proxies de un archivo de texto. Formato por línea:

        scheme://host:port[#country=ES][#user=...][#pass=...]

    Ej: http://1.2.3.4:8080#country=ES
        socks5://user:pass@10.0.0.1:1080
    """

    def __init__(
        self,
        *,
        path: Path,
        healthcheck_url: str,
        quarantine_duration_seconds: int = 300,
    ) -> None:
        self._path = path
        self._healthcheck_url = healthcheck_url
        self._quarantine_duration = timedelta(seconds=quarantine_duration_seconds)
        self._proxies: list[ProxyEndpoint] = []
        self._health: dict[ProxyEndpoint, _ProxyHealth] = defaultdict(_ProxyHealth)
        self._lock = asyncio.Lock()
        self._loaded = False

    async def acquire(self, *, country: Country | None = None) -> ProxyEndpoint | None:
        await self._ensure_loaded()
        async with self._lock:
            candidates = [
                p
                for p in self._proxies
                if not self._health[p].is_quarantined()
                and (country is None or p.country == country or p.country is None)
            ]
        if not candidates:
            return None
        # Sort por mejor score (más éxitos, menos fallos).
        candidates.sort(
            key=lambda p: (
                self._health[p].failures,
                -self._health[p].successes,
            ),
        )
        return candidates[0]

    async def report_failure(self, proxy: ProxyEndpoint, reason: str) -> None:  # noqa: ARG002
        async with self._lock:
            health = self._health[proxy]
            health.failures += 1
            health.last_failure_at = datetime.now(UTC)
            if health.failures >= 3:
                health.quarantined_until = datetime.now(UTC) + self._quarantine_duration
                health.failures = 0  # reset tras cuarentena

    async def report_success(self, proxy: ProxyEndpoint) -> None:
        async with self._lock:
            self._health[proxy].successes += 1

    async def healthcheck_all(self, *, timeout_seconds: float = 5.0) -> None:
        """Comprueba qué proxies responden. Pone los muertos en cuarentena."""
        await self._ensure_loaded()

        async def check_one(proxy: ProxyEndpoint) -> None:
            try:
                async with httpx.AsyncClient(
                    proxy=proxy.as_url(),
                    timeout=timeout_seconds,
                ) as client:
                    resp = await client.get(self._healthcheck_url)
                    if resp.status_code == 200:
                        await self.report_success(proxy)
                        return
            except (httpx.RequestError, httpx.HTTPStatusError):
                pass
            await self.report_failure(proxy, reason="healthcheck_failed")

        async with asyncio.TaskGroup() as tg:
            for p in self._proxies:
                tg.create_task(check_one(p))

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not await anyio.Path(self._path).exists():
            self._loaded = True
            return
        async with await anyio.open_file(self._path) as f:
            content = await f.read()
        for raw in content.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            self._proxies.append(self._parse(line))
        self._loaded = True

    @staticmethod
    def _parse(line: str) -> ProxyEndpoint:
        url_part, _, meta_part = line.partition("#")
        # url_part: scheme://[user:pass@]host:port
        scheme, _, rest = url_part.partition("://")
        creds, _, hostport = rest.rpartition("@") if "@" in rest else ("", "", rest)
        host, _, port_str = hostport.rpartition(":")
        username, password = ([*creds.split(":", 1), ""])[:2] if creds else (None, None)

        country: Country | None = None
        for kv in meta_part.split("#"):
            if kv.startswith("country="):
                country = Country(kv.split("=", 1)[1].upper())

        return ProxyEndpoint(
            scheme=scheme,
            host=host,
            port=int(port_str),
            username=username or None,
            password=password or None,
            country=country,
        )
