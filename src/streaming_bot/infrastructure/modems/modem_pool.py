"""ModemPool: implementacion del puerto IModemPool.

Responsabilidades:
- Mantener referencias en memoria de los modems persistidos en `IModemRepository`.
- Asignar (`acquire`) modems READY del pais correcto respetando cooldowns y
  cuotas diarias.
- Liberar (`release`) marcando COOLING_DOWN y agendando rotacion de IP.
- Health/Quarantine logica: clasificar `report_failure` por tipo de error.
- Background tasks:
  * `_rotation_worker`: rota IP de modems COOLING_DOWN tras 5 min.
  * `_health_worker`: re-introduce UNHEALTHY al pool cada 5 min via health_check.

Concurrencia:
- Un asyncio.Semaphore por modem garantiza uso exclusivo del recurso fisico.
- Un asyncio.Lock global protege transiciones de estado del pool.
- Las llamadas a `IModemRepository.update` son fire-and-forget desde transiciones
  (los background tasks reintentan al siguiente ciclo si fallan).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from streaming_bot.domain.modem import Modem, ModemState
from streaming_bot.domain.value_objects import Country, ProxyEndpoint

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

    from streaming_bot.domain.ports.modem_driver import IModemDriver
    from streaming_bot.domain.ports.modem_repo import IModemRepository
    from streaming_bot.infrastructure.modems.interface_binder import LinuxInterfaceBinder
    from streaming_bot.infrastructure.modems.local_proxy_runner import DanteProxyRunner

# Patrones de razones que requieren cuarentena / unhealthy. Documentadas para
# que el operador entienda la clasificacion sin leer el codigo.
_QUARANTINE_PATTERNS: tuple[str, ...] = ("captcha", "flagged", "banned", "blocked", "shadowban")
_UNHEALTHY_PATTERNS: tuple[str, ...] = ("timeout", "conn_reset", "unreachable", "tls_error")

_QUARANTINE_REGEX: re.Pattern[str] = re.compile("|".join(_QUARANTINE_PATTERNS), re.IGNORECASE)
_UNHEALTHY_REGEX: re.Pattern[str] = re.compile("|".join(_UNHEALTHY_PATTERNS), re.IGNORECASE)

_ROTATION_AGE_SECONDS: float = 300.0  # rotamos IP de COOLING_DOWN tras 5 min
_HEALTH_CHECK_INTERVAL_S: float = 300.0  # cada 5 min revisamos UNHEALTHY
_ROTATION_LOOP_TICK_S: float = 5.0
_ACQUIRE_POLL_INTERVAL_S: float = 0.25

# Rango de puertos locales (uno por modem). Spec: 10001..10030.
_LOCAL_PROXY_PORT_BASE: int = 10000
_LOCAL_PROXY_PORT_MAX: int = 10999


@dataclass(slots=True)
class _ModemSlot:
    """Estado runtime de un modem dentro del pool (no persistido)."""

    modem: Modem
    semaphore: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))
    local_proxy_port: int | None = None
    iface: str | None = None
    last_failed_at: datetime | None = None


class ModemPool:
    """Pool concurrente de modems fisicos."""

    def __init__(
        self,
        *,
        driver: IModemDriver,
        repository: IModemRepository,
        interface_binder: LinuxInterfaceBinder,
        proxy_runner: DanteProxyRunner,
        logger: BoundLogger,
        local_proxy_port_base: int = _LOCAL_PROXY_PORT_BASE,
    ) -> None:
        self._driver = driver
        self._repo = repository
        self._binder = interface_binder
        self._proxy_runner = proxy_runner
        self._logger = logger
        self._port_base = local_proxy_port_base
        self._slots: dict[str, _ModemSlot] = {}
        self._lock = asyncio.Lock()
        self._loaded = False
        self._port_cursor: int = 1
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._stopping = asyncio.Event()

    # ----------------------------- inicializacion -----------------------------

    async def load_from_repository(self) -> None:
        """Carga modems persistidos en memoria (idempotente)."""
        async with self._lock:
            if self._loaded:
                return
            modems = await self._repo.list_all()
            for modem in modems:
                self._slots[modem.id] = _ModemSlot(modem=modem)
            self._loaded = True
        self._logger.info("modem_pool_loaded", count=len(self._slots))

    async def start(self) -> None:
        """Arranca background workers (rotation + health)."""
        await self.load_from_repository()
        self._stopping.clear()
        self._spawn_task(self._rotation_worker(), name="rotation_worker")
        self._spawn_task(self._health_worker(), name="health_worker")

    async def stop(self) -> None:
        """Detiene background workers y libera recursos del runner."""
        self._stopping.set()
        for task in list(self._background_tasks):
            task.cancel()
        for task in list(self._background_tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._background_tasks.clear()
        await self._proxy_runner.stop_all()

    # ----------------------------- IModemPool API -----------------------------

    async def acquire(
        self,
        *,
        country: Country,
        timeout_seconds: float = 30.0,
    ) -> Modem | None:
        """Devuelve un modem READY del pais o None si timeout. Bloquea su semaforo."""
        await self.load_from_repository()
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while True:
            slot = await self._pick_slot(country)
            if slot is not None:
                acquired = await self._try_acquire_slot(slot)
                if acquired is not None:
                    return acquired
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                self._logger.info("modem_acquire_timeout", country=country.value)
                return None
            await asyncio.sleep(min(_ACQUIRE_POLL_INTERVAL_S, remaining))

    async def release(
        self,
        modem: Modem,
        *,
        streams_served: int = 0,
        rotate_ip: bool = True,
    ) -> None:
        """Marca COOLING_DOWN y opcionalmente lanza rotacion en background."""
        slot = await self._require_slot(modem.id)
        async with self._lock:
            try:
                slot.modem.release(streams_served=streams_served)
            except ValueError:
                self._logger.warning(
                    "modem_release_invalid_state",
                    modem_id=modem.id,
                    state=slot.modem.state.value,
                )
            await self._repo.update(slot.modem)
        slot.semaphore.release()
        if rotate_ip:
            self._spawn_task(self._do_rotate_ip(slot), name=f"rotate-{modem.id}")

    async def report_failure(self, modem: Modem, reason: str) -> None:
        """Clasifica el fallo: captcha/banned -> quarantine; timeout -> unhealthy."""
        slot = await self._require_slot(modem.id)
        async with self._lock:
            slot.last_failed_at = datetime.now(UTC)
            if _QUARANTINE_REGEX.search(reason):
                slot.modem.quarantine(reason)
                self._logger.warning(
                    "modem_quarantined",
                    modem_id=modem.id,
                    reason=reason,
                )
            elif _UNHEALTHY_REGEX.search(reason):
                slot.modem.mark_unhealthy(reason)
                self._logger.warning(
                    "modem_unhealthy",
                    modem_id=modem.id,
                    reason=reason,
                )
            else:
                # Razon desconocida: marcamos unhealthy por precaucion (fail-closed).
                slot.modem.mark_unhealthy(reason)
                self._logger.warning(
                    "modem_unknown_failure",
                    modem_id=modem.id,
                    reason=reason,
                )
            await self._repo.update(slot.modem)
        # Si estaba IN_USE el caller seguramente sigue manteniendo el semaforo;
        # por seguridad lo liberamos para no leak-ear el slot.
        if slot.semaphore.locked():
            slot.semaphore.release()

    async def list_all(self) -> list[Modem]:
        await self.load_from_repository()
        async with self._lock:
            return [slot.modem for slot in self._slots.values()]

    async def list_available(self, *, country: Country | None = None) -> list[Modem]:
        await self.load_from_repository()
        async with self._lock:
            return [
                slot.modem
                for slot in self._slots.values()
                if slot.modem.is_available
                and (country is None or slot.modem.country == country)
                and slot.modem.can_assign_now()
            ]

    async def reset_daily_counters(self) -> None:
        """Resetea contadores diarios. Persistencia best-effort."""
        await self.load_from_repository()
        async with self._lock:
            for slot in self._slots.values():
                slot.modem.reset_daily_counters()
                await self._repo.update(slot.modem)
        self._logger.info("modem_pool_reset_daily_counters", count=len(self._slots))

    def stream_proxy_endpoints(
        self,
        *,
        country: Country | None = None,
    ) -> AsyncIterator[ProxyEndpoint]:
        """Iterador async de ProxyEndpoints listos para usar."""
        return self._stream_endpoints(country)

    # ----------------------------- helpers internos -----------------------------

    async def get_local_proxy_port(self, modem_id: str) -> int:
        """Asigna (o devuelve) el puerto local del proxy SOCKS5 para este modem."""
        slot = await self._require_slot(modem_id)
        async with self._lock:
            if slot.local_proxy_port is None:
                slot.local_proxy_port = self._allocate_local_port()
            return slot.local_proxy_port

    async def to_proxy_endpoint(self, modem: Modem) -> ProxyEndpoint:
        """Construye el endpoint local SOCKS5 que el browser usara para este modem."""
        port = await self.get_local_proxy_port(modem.id)
        return modem.to_proxy_endpoint(local_proxy_port=port)

    async def _stream_endpoints(self, country: Country | None) -> AsyncIterator[ProxyEndpoint]:
        for modem in await self.list_available(country=country):
            yield await self.to_proxy_endpoint(modem)

    async def _pick_slot(self, country: Country) -> _ModemSlot | None:
        async with self._lock:
            candidates = [
                slot
                for slot in self._slots.values()
                if slot.modem.country == country
                and slot.modem.is_available
                and slot.modem.can_assign_now()
                and not slot.semaphore.locked()
            ]
        if not candidates:
            return None
        # Preferimos el que lleva mas tiempo sin usarse (max idle) -> mejor rotacion.
        candidates.sort(key=_idle_score)
        return candidates[0]

    async def _try_acquire_slot(self, slot: _ModemSlot) -> Modem | None:
        # Intento no bloqueante: si otro coroutine se nos adelanto, devolvemos None.
        if not await _acquire_semaphore_nowait(slot.semaphore):
            return None
        async with self._lock:
            if not slot.modem.is_available or not slot.modem.can_assign_now():
                slot.semaphore.release()
                return None
            try:
                slot.modem.assign()
            except ValueError:
                slot.semaphore.release()
                return None
            await self._repo.update(slot.modem)
            return slot.modem

    async def _require_slot(self, modem_id: str) -> _ModemSlot:
        await self.load_from_repository()
        async with self._lock:
            slot = self._slots.get(modem_id)
        if slot is None:
            raise KeyError(f"modem {modem_id} no esta registrado en el pool")
        return slot

    def _allocate_local_port(self) -> int:
        # Reservamos puertos secuenciales arrancando en port_base+1 hasta MAX.
        used = {slot.local_proxy_port for slot in self._slots.values() if slot.local_proxy_port}
        candidate = self._port_base + self._port_cursor
        while candidate in used and candidate <= _LOCAL_PROXY_PORT_MAX:
            self._port_cursor += 1
            candidate = self._port_base + self._port_cursor
        if candidate > _LOCAL_PROXY_PORT_MAX:
            raise RuntimeError("se agoto el rango de puertos locales para proxies de modem")
        self._port_cursor += 1
        return candidate

    async def _do_rotate_ip(self, slot: _ModemSlot) -> None:
        # Decision: la rotacion vive fuera del path critico de release() para
        # devolver al caller (orquestador de streaming) lo antes posible.
        async with self._lock:
            slot.modem.begin_rotation()
            await self._repo.update(slot.modem)
        new_ip: str | None = None
        try:
            new_ip = await self._driver.rotate_ip(slot.modem)
        except Exception as exc:
            self._logger.error(
                "modem_rotate_worker_error",
                modem_id=slot.modem.id,
                error=str(exc),
            )
        async with self._lock:
            slot.modem.complete_rotation(new_public_ip=new_ip)
            await self._repo.update(slot.modem)

    async def _rotation_worker(self) -> None:
        """Cada N segundos rota IP a modems en COOLING_DOWN con >= 300s parados."""
        while not self._stopping.is_set():
            try:
                await asyncio.sleep(_ROTATION_LOOP_TICK_S)
            except asyncio.CancelledError:
                return
            async with self._lock:
                slots = list(self._slots.values())
            for slot in slots:
                if slot.modem.state != ModemState.COOLING_DOWN:
                    continue
                if slot.modem.last_used_at is None:
                    continue
                idle = datetime.now(UTC) - slot.modem.last_used_at
                if idle >= timedelta(seconds=_ROTATION_AGE_SECONDS):
                    self._spawn_task(
                        self._rotate_then_ready(slot),
                        name=f"rotate-cooling-{slot.modem.id}",
                    )

    async def _rotate_then_ready(self, slot: _ModemSlot) -> None:
        await self._do_rotate_ip(slot)

    async def _health_worker(self) -> None:
        """Cada 5 minutos revisa modems UNHEALTHY y los re-incorpora si responden."""
        while not self._stopping.is_set():
            try:
                await asyncio.sleep(_HEALTH_CHECK_INTERVAL_S)
            except asyncio.CancelledError:
                return
            async with self._lock:
                unhealthy = [
                    slot
                    for slot in self._slots.values()
                    if slot.modem.state == ModemState.UNHEALTHY
                ]
            for slot in unhealthy:
                healthy = False
                try:
                    healthy = await self._driver.health_check(slot.modem)
                except Exception as exc:
                    self._logger.warning(
                        "modem_health_check_error",
                        modem_id=slot.modem.id,
                        error=str(exc),
                    )
                if healthy:
                    async with self._lock:
                        slot.modem.mark_ready()
                        slot.modem.last_health_check_at = datetime.now(UTC)
                        await self._repo.update(slot.modem)
                    self._logger.info("modem_recovered", modem_id=slot.modem.id)

    def _spawn_task(self, coro: object, *, name: str) -> None:
        # `coro` se anota como object porque mypy no infiere bien Coroutine[..., None] sin overload.
        task: asyncio.Task[None] = asyncio.create_task(coro, name=name)  # type: ignore[arg-type]
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)


def _idle_score(slot: _ModemSlot) -> float:
    """Devuelve segundos desde el ultimo uso (0 si nunca se uso)."""
    if slot.modem.last_used_at is None:
        return float("inf")
    return -((datetime.now(UTC) - slot.modem.last_used_at).total_seconds())


async def _acquire_semaphore_nowait(semaphore: asyncio.Semaphore) -> bool:
    """Intento no-bloqueante de adquirir un asyncio.Semaphore (timeout muy corto)."""
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=0.01)
    except TimeoutError:
        return False
    return True
