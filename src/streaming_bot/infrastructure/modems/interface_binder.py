"""Bindings de interfaz para tunelar trafico de un puerto local via la NIC del modem.

Idea: cada modem fisico expone una interfaz (wwan0, ppp1, eth1, ...). Para que el
trafico de un proxy local salga por esa interfaz creamos:

1. Una tabla de routing dedicada (`ip route add default dev <iface> table <id>`).
2. Una regla `ip rule` que envia el trafico que sale por puerto local <port>
   (o sourceado por ip de iface) a esa tabla.
3. Opcionalmente reglas iptables `MARK` + `policy routing`.

Esto solo es viable en Linux con CAP_NET_ADMIN (sudo). En macOS / Windows no existe
analogo trivial; se loguea un warning y se opera en modo "fake binding" (el proxy
local existe pero el trafico sale por la interfaz default del SO). Los tests y dev
local se apoyan en este fallback.
"""

from __future__ import annotations

import asyncio
import platform
import shutil
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

# Rango de tablas de routing para evitar colisionar con el SO (1..251 son del kernel).
_ROUTE_TABLE_BASE: int = 200
_FWMARK_BASE: int = 0x1000

_PROC_TIMEOUT: float = 5.0


@dataclass(slots=True)
class _Binding:
    """Estado de un binding activo (para poder revertirlo)."""

    iface: str
    local_port: int
    table_id: int
    fwmark: int
    bind_address: str | None
    commands_executed: list[list[str]] = field(default_factory=list)


class LinuxInterfaceBinder:
    """Aplica reglas iptables/ip-route para que cierto puerto salga por una NIC.

    En SOs no-Linux (Darwin, Windows) o sin sudo se degrada a "fake binding": guarda
    el binding en memoria pero no ejecuta comandos de sistema. Asi los tests + macs
    de desarrollo funcionan sin red real.
    """

    def __init__(
        self,
        *,
        logger: BoundLogger,
        sudo_command: str = "sudo",
        fake_in_non_linux: bool = True,
    ) -> None:
        self._logger = logger
        self._sudo = sudo_command
        self._fake = fake_in_non_linux and not _is_linux()
        self._bindings: dict[str, _Binding] = {}
        self._lock = asyncio.Lock()
        self._next_table_offset: int = 0

    @property
    def is_fake(self) -> bool:
        return self._fake

    async def bind(self, modem_id: str, iface: str, local_port: int) -> None:
        """Crea reglas para que `local_port` salga por `iface`.

        En modo fake solo registra el binding y loguea warning. En Linux
        ejecuta `ip route add ... table N`, `ip rule add fwmark ...` y
        `iptables -t mangle -A OUTPUT --dport <port> -j MARK --set-mark`.
        """
        async with self._lock:
            if modem_id in self._bindings:
                # Idempotencia: si ya existe binding para ese modem, lo reutilizamos.
                return
            table_id = _ROUTE_TABLE_BASE + self._next_table_offset
            fwmark = _FWMARK_BASE + self._next_table_offset
            self._next_table_offset += 1
            bind_address = await self._resolve_bind_address(iface)
            binding = _Binding(
                iface=iface,
                local_port=local_port,
                table_id=table_id,
                fwmark=fwmark,
                bind_address=bind_address,
            )
            if self._fake:
                self._logger.warning(
                    "interface_binder_fake_mode",
                    modem_id=modem_id,
                    iface=iface,
                    local_port=local_port,
                    reason="non_linux_or_no_sudo",
                )
            else:
                await self._apply_linux_rules(binding)
            self._bindings[modem_id] = binding

    async def unbind(self, modem_id: str) -> None:
        """Revierte las reglas creadas en bind()."""
        async with self._lock:
            binding = self._bindings.pop(modem_id, None)
            if binding is None:
                return
            if self._fake:
                return
            await self._revert_linux_rules(binding)

    def get_bind_address(self, modem_id: str) -> str | None:
        """Devuelve la IP local del modem (para sourceo del proxy)."""
        binding = self._bindings.get(modem_id)
        return None if binding is None else binding.bind_address

    async def _apply_linux_rules(self, binding: _Binding) -> None:
        # Decision: usar fwmark+ip rule en vez de SO_BINDTODEVICE para no requerir CAP_NET_RAW
        # en el proxy. El proxy local marcara los paquetes via iptables MARK por --dport.
        table = str(binding.table_id)
        fwmark = hex(binding.fwmark)
        commands: list[list[str]] = [
            ["ip", "route", "replace", "default", "dev", binding.iface, "table", table],
            ["ip", "rule", "add", "fwmark", fwmark, "table", table],
            [
                "iptables",
                "-t",
                "mangle",
                "-A",
                "OUTPUT",
                "-p",
                "tcp",
                "--sport",
                str(binding.local_port),
                "-j",
                "MARK",
                "--set-mark",
                hex(binding.fwmark),
            ],
        ]
        for cmd in commands:
            await self._run_with_sudo(cmd)
            binding.commands_executed.append(cmd)

    async def _revert_linux_rules(self, binding: _Binding) -> None:
        commands: list[list[str]] = [
            [
                "iptables",
                "-t",
                "mangle",
                "-D",
                "OUTPUT",
                "-p",
                "tcp",
                "--sport",
                str(binding.local_port),
                "-j",
                "MARK",
                "--set-mark",
                hex(binding.fwmark),
            ],
            ["ip", "rule", "del", "fwmark", hex(binding.fwmark), "table", str(binding.table_id)],
            ["ip", "route", "flush", "table", str(binding.table_id)],
        ]
        for cmd in commands:
            # Best-effort: si falla algun revert no abortamos el resto.
            try:
                await self._run_with_sudo(cmd)
            except RuntimeError as exc:
                self._logger.warning(
                    "interface_binder_revert_partial_failure",
                    cmd=cmd,
                    error=str(exc),
                )

    async def _resolve_bind_address(self, iface: str) -> str | None:
        """Obtiene la IP IPv4 actual de la interfaz (best effort)."""
        if self._fake:
            return None
        if shutil.which("ip") is None:
            return None
        try:
            stdout = await self._run(["ip", "-4", "-o", "addr", "show", "dev", iface])
        except RuntimeError:
            return None
        for line in stdout.splitlines():
            tokens = line.split()
            if "inet" in tokens:
                idx = tokens.index("inet")
                if idx + 1 < len(tokens):
                    return tokens[idx + 1].split("/", 1)[0]
        return None

    async def _run_with_sudo(self, cmd: list[str]) -> str:
        full_cmd = [self._sudo, "-n", *cmd] if self._sudo else cmd
        return await self._run(full_cmd)

    @staticmethod
    async def _run(cmd: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_PROC_TIMEOUT)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"command timeout: {' '.join(cmd)}") from exc
        if proc.returncode != 0:
            stderr_text = stderr.decode(errors="replace").strip()
            raise RuntimeError(
                f"command failed ({proc.returncode}): {' '.join(cmd)} -- {stderr_text}",
            )
        return stdout.decode(errors="replace")


def _is_linux() -> bool:
    """Detecta Linux (excluye WSL si no esta enabled). Robust contra mocking en tests."""
    return sys.platform.startswith("linux") and platform.system() == "Linux"
