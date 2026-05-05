"""``LocalStockFootageRepository``: lookup local de stock footage por nicho.

Layout esperado en disco::

    data/stock/
        lo-fi/
            metadata.json     # ver formato abajo
            clips/
                rain-window-01.mp4
                rain-window-02.mp4
                ...
        sleep/
            metadata.json
            clips/
                ...
        focus/
            metadata.json
            clips/
                ...

``metadata.json`` (un objeto JSON por nicho)::

    {
      "niche": "lo-fi",
      "clips": [
        {"file": "rain-window-01.mp4", "mood": "rainy", "duration_s": 12},
        {"file": "rain-window-02.mp4", "mood": "rainy", "duration_s": 18},
        {"file": "cafe-warm-01.mp4",   "mood": "cozy",  "duration_s": 25}
      ]
    }

Reglas:
- Pool minimo recomendado por nicho: 50 clips de 10-30s cada uno.
- Cada clip vertical 9:16 (1080x1920) o reescalable a 9:16 sin recortar
  cabezas (frames "neutros": paisajes, abstractos, manos en escritorio,
  ventanas con lluvia, animaciones de luz, etc).
- v1 NO incluye los clips ni el metadata.json: documenta el formato
  esperado y lanza ``FileNotFoundError`` si el nicho no existe.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger


@dataclass(frozen=True, slots=True)
class StockClip:
    """Clip individual con ruta absoluta + metadata."""

    path: Path
    mood: str | None
    duration_seconds: int


class LocalStockFootageRepository:
    """Implementacion de ``IStockFootageRepository`` con lookup en disco."""

    def __init__(
        self,
        *,
        root_dir: Path,
        rng: secrets.SystemRandom | None = None,
        logger: BoundLogger | None = None,
    ) -> None:
        self._root = root_dir
        self._rng = rng or secrets.SystemRandom()
        self._log: BoundLogger = logger or structlog.get_logger("meta.stock_footage")
        self._cache: dict[str, list[StockClip]] = {}

    async def pick_clip(self, *, niche: str, mood: str | None = None) -> Path:
        clips = self._load_niche(niche)
        if not clips:
            raise FileNotFoundError(
                f"no hay clips para niche='{niche}' en {self._root / niche}",
            )
        candidates = clips
        if mood:
            filtered = [c for c in clips if c.mood == mood]
            if filtered:
                candidates = filtered
        chosen = self._rng.choice(candidates)
        self._log.debug(
            "stock.pick",
            niche=niche,
            mood=mood,
            chosen=chosen.path.name,
            pool_size=len(candidates),
        )
        return chosen.path

    def _load_niche(self, niche: str) -> list[StockClip]:
        if niche in self._cache:
            return self._cache[niche]

        niche_dir = self._root / niche
        metadata_path = niche_dir / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(
                f"metadata.json no encontrado: {metadata_path}. "
                "Crear segun docstring del modulo.",
            )

        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise FileNotFoundError(
                f"metadata.json invalido en {metadata_path}: {exc}",
            ) from exc

        raw_clips = data.get("clips") or []
        clips: list[StockClip] = []
        for entry in raw_clips:
            file_name = entry.get("file")
            if not file_name:
                continue
            clip_path = niche_dir / "clips" / file_name
            clips.append(
                StockClip(
                    path=clip_path,
                    mood=entry.get("mood"),
                    duration_seconds=int(entry.get("duration_s") or 0),
                ),
            )
        self._cache[niche] = clips
        self._log.info("stock.loaded", niche=niche, count=len(clips))
        return clips
