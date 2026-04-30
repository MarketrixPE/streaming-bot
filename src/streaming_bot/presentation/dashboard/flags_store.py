"""Persistencia minima de flags de UI para el dashboard.

`DashboardFlagsStore` guarda en `data/dashboard_flags.json` el estado de
los toggles de operador (pausa del piloto, ultima rotacion forzada, etc.)
para que sobrevivan a recargas de pagina y reinicios del proceso de
Streamlit.

Diseno:
- Sin dependencias: solo `pathlib` + `json`. Resistente a fallos: si el
  archivo no existe o esta corrupto, devuelve flags por defecto.
- Atomico en escritura: archivo temp + `os.replace` para evitar corrupcion
  durante writes simultaneos (Streamlit corre handlers en threads).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock


@dataclass(slots=True)
class DashboardFlags:
    """Snapshot de flags persistidos del dashboard.

    Attributes:
        pilot_paused: ``True`` si el operador pauso el piloto.
        pilot_paused_reason: motivo libre del operador.
        pilot_paused_at: timestamp ISO del pause.
        last_force_rotation_at: ISO de la ultima rotacion forzada de modems.
        custom: dict abierto para extensiones futuras sin migrar.
    """

    pilot_paused: bool = False
    pilot_paused_reason: str = ""
    pilot_paused_at: str | None = None
    last_force_rotation_at: str | None = None
    custom: dict[str, str] = field(default_factory=dict)


class DashboardFlagsStore:
    """Lectura/escritura de flags JSON con lock por proceso.

    Args:
        path: ruta al JSON. Por defecto ``data/dashboard_flags.json``.
    """

    def __init__(self, *, path: Path = Path("./data/dashboard_flags.json")) -> None:
        self._path = path
        self._lock = Lock()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> DashboardFlags:
        """Carga flags. Si no existe el archivo, devuelve defaults."""
        if not self._path.exists():
            return DashboardFlags()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DashboardFlags()
        if not isinstance(raw, dict):
            return DashboardFlags()
        return DashboardFlags(
            pilot_paused=bool(raw.get("pilot_paused", False)),
            pilot_paused_reason=str(raw.get("pilot_paused_reason", "")),
            pilot_paused_at=raw.get("pilot_paused_at") or None,
            last_force_rotation_at=raw.get("last_force_rotation_at") or None,
            custom={str(k): str(v) for k, v in (raw.get("custom") or {}).items()},
        )

    def save(self, flags: DashboardFlags) -> None:
        """Persiste flags de forma atomica."""
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(asdict(flags), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._path)

    def pause_pilot(self, reason: str) -> DashboardFlags:
        """Marca el piloto como pausado y devuelve el snapshot actualizado."""
        flags = self.load()
        flags.pilot_paused = True
        flags.pilot_paused_reason = reason.strip()
        flags.pilot_paused_at = datetime.now(UTC).isoformat()
        self.save(flags)
        return flags

    def resume_pilot(self) -> DashboardFlags:
        """Quita la pausa del piloto."""
        flags = self.load()
        flags.pilot_paused = False
        flags.pilot_paused_reason = ""
        flags.pilot_paused_at = None
        self.save(flags)
        return flags

    def mark_force_rotation(self) -> DashboardFlags:
        """Registra una rotacion forzada (placeholder hasta wire al pool real)."""
        flags = self.load()
        flags.last_force_rotation_at = datetime.now(UTC).isoformat()
        self.save(flags)
        return flags
