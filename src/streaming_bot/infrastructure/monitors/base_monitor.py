"""Base abstracta de los monitores de distribuidores.

Centraliza:
- Keywords de deteccion por categoria (modificables sin tocar logica).
- Helpers de parsing HTML con selectolax.
- Manejo de ``storage_state`` persistente por plataforma para skip de login.
- Logger structlog inyectado.

Cada subclase implementa:
- ``platform`` (override de la property del puerto).
- ``login_and_scrape``
- ``check_emails``
- ``is_authenticated``
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from selectolax.parser import HTMLParser
from structlog.stdlib import BoundLogger

from streaming_bot.domain.ports.browser_rich import IRichBrowserDriver
from streaming_bot.domain.ports.distributor_monitor import (
    AlertCategory,
    AlertSeverity,
    DistributorAlert,
    DistributorPlatform,
)
from streaming_bot.domain.value_objects import Fingerprint

# ──────────────────────────────────────────────────────────────────────────────
# Keywords por categoria. Lista actualizable; matching case-insensitive.
# ──────────────────────────────────────────────────────────────────────────────

KEYWORDS_FILTERED_STREAMS: tuple[str, ...] = (
    "filtered streams",
    "stream manipulation",
    "artificial streams",
    "fake streams",
    "fraudulent streams",
    "streams may have been filtered",
    "streams have been removed",
    "removed streams",
    "anti-fraud",
    "spotify removed",
    "platform removed",
)

KEYWORDS_STREAM_MANIPULATION: tuple[str, ...] = (
    "stream manipulation",
    "stream banker",
    "manipulation detected",
    "suspicious activity",
    "abnormal pattern",
    "abnormal listening",
    "violates our terms",
    "violation of our terms",
    "policy violation",
)

KEYWORDS_PAYMENT_HOLD: tuple[str, ...] = (
    "payment hold",
    "payments on hold",
    "payments paused",
    "earnings withheld",
    "earnings on hold",
    "clawback",
    "chargeback",
    "withhold royalties",
    "royalties withheld",
)

KEYWORDS_ACCOUNT_REVIEW: tuple[str, ...] = (
    "account under review",
    "manual review",
    "your account is being reviewed",
    "account review",
    "additional verification",
    "we need to verify",
)

KEYWORDS_ACCOUNT_CLOSED: tuple[str, ...] = (
    "account closed",
    "account terminated",
    "account suspended",
    "account banned",
    "permanently disabled",
    "we have closed your account",
)


# Umbral por defecto para flag de caida mes-mes (porcentaje negativo).
DEFAULT_REVENUE_DROP_THRESHOLD_PCT = -40.0
DEFAULT_LISTENERS_DROP_THRESHOLD_PCT = -30.0


class BaseDistributorMonitor(ABC):
    """Esqueleto comun de los monitores.

    Provee:
    - Carga/persistencia de ``storage_state`` JSON por plataforma.
    - Helpers ``_extract_text``, ``_match_keywords`` y construccion de alertas.
    - ``platform`` property requerida por ``IDistributorMonitor``.

    Args:
        browser_driver: driver rico para navegar dashboards (``IRichBrowserDriver``).
        fingerprint: huella coherente con el proxy del operador.
        storage_state_path: archivo JSON donde se persiste cookies/localStorage.
        logger: logger structlog (BoundLogger). Cada subclase recibe el suyo.
    """

    #: Plataforma asociada. Las subclases la sobreescriben con un ``ClassVar``.
    PLATFORM: DistributorPlatform

    def __init__(
        self,
        *,
        browser_driver: IRichBrowserDriver,
        fingerprint: Fingerprint,
        storage_state_path: Path,
        logger: BoundLogger,
    ) -> None:
        self._browser_driver = browser_driver
        self._fingerprint = fingerprint
        self._storage_state_path = storage_state_path
        self._logger = logger.bind(monitor=self.PLATFORM.value)

    # ── Property requerida por el Protocol IDistributorMonitor ───────────────
    @property
    def platform(self) -> DistributorPlatform:
        return self.PLATFORM

    # ── Storage state ────────────────────────────────────────────────────────
    def _load_storage_state(self) -> dict[str, Any] | None:
        """Carga el storage_state del filesystem si existe."""
        if not self._storage_state_path.exists():
            return None
        try:
            with self._storage_state_path.open("r", encoding="utf-8") as fh:
                data: dict[str, Any] = json.load(fh)
                return data
        except (OSError, json.JSONDecodeError) as exc:
            self._logger.warning(
                "storage_state_load_failed",
                path=str(self._storage_state_path),
                error=str(exc),
            )
            return None

    def _save_storage_state(self, state: dict[str, Any]) -> None:
        """Persiste el storage_state actualizado al filesystem."""
        self._storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._storage_state_path.open("w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            self._logger.warning(
                "storage_state_save_failed",
                path=str(self._storage_state_path),
                error=str(exc),
            )

    # ── Helpers de parsing HTML con selectolax ───────────────────────────────
    @staticmethod
    def _extract_text(html: str, css: str) -> str | None:
        """Devuelve el texto plano del primer match del selector CSS, o None."""
        if not html:
            return None
        try:
            tree = HTMLParser(html)
        except (ValueError, TypeError):
            return None
        node = tree.css_first(css)
        if node is None:
            return None
        return node.text(strip=True) or None

    @staticmethod
    def _extract_all_texts(html: str, css: str) -> list[str]:
        """Devuelve todos los textos coincidentes con el selector."""
        if not html:
            return []
        try:
            tree = HTMLParser(html)
        except (ValueError, TypeError):
            return []
        return [node.text(strip=True) for node in tree.css(css) if node.text(strip=True)]

    @staticmethod
    def _match_keywords(text: str, keywords: list[str] | tuple[str, ...]) -> bool:
        """¿El texto contiene alguno de los keywords (case-insensitive)?"""
        if not text:
            return False
        haystack = text.lower()
        return any(kw.lower() in haystack for kw in keywords)

    @staticmethod
    def _matched_keywords(text: str, keywords: list[str] | tuple[str, ...]) -> list[str]:
        """Devuelve la lista de keywords concretos encontrados en el texto."""
        if not text:
            return []
        haystack = text.lower()
        return [kw for kw in keywords if kw.lower() in haystack]

    @staticmethod
    def _parse_money_value(raw: str) -> float | None:
        """Convierte ``$1,234.56`` o ``1.234,56 EUR`` a float. None si imposible."""
        if not raw:
            return None
        cleaned = re.sub(r"[^\d,.\-]", "", raw)
        if not cleaned:
            return None
        # Detectamos el separador decimal heuristicamente: el ultimo separador.
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            # Si solo hay coma, asumimos decimal europeo solo si tiene 1-2 decimales.
            if re.fullmatch(r"-?\d+,\d{1,2}", cleaned):
                cleaned = cleaned.replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        try:
            return float(cleaned)
        except ValueError:
            return None

    @staticmethod
    def _parse_int_value(raw: str) -> int | None:
        """Convierte ``"1,234,567"`` o ``"12.4M"`` a int aproximado."""
        if not raw:
            return None
        text = raw.strip().lower()
        multiplier = 1
        if text.endswith("k"):
            multiplier = 1_000
            text = text[:-1]
        elif text.endswith("m"):
            multiplier = 1_000_000
            text = text[:-1]
        elif text.endswith("b"):
            multiplier = 1_000_000_000
            text = text[:-1]
        cleaned = re.sub(r"[^\d.\-]", "", text)
        if not cleaned:
            return None
        try:
            return int(float(cleaned) * multiplier)
        except ValueError:
            return None

    # ── Construccion de alertas ──────────────────────────────────────────────
    def _build_alert(
        self,
        *,
        severity: AlertSeverity,
        category: AlertCategory,
        message: str,
        evidence: str = "",
        affected_song_titles: tuple[str, ...] = (),
    ) -> DistributorAlert:
        """Construye un ``DistributorAlert`` con timestamp UTC."""
        return DistributorAlert(
            platform=self.PLATFORM,
            severity=severity,
            category=category,
            detected_at=datetime.now(UTC),
            message=message,
            affected_song_titles=affected_song_titles,
            raw_evidence=evidence[:5_000],  # se trunca para evitar logs gigantes
        )

    # ── Contrato del puerto ──────────────────────────────────────────────────
    @abstractmethod
    async def login_and_scrape(self) -> list[DistributorAlert]: ...

    @abstractmethod
    async def check_emails(self, since: datetime | None = None) -> list[DistributorAlert]: ...

    @abstractmethod
    async def is_authenticated(self) -> bool: ...
