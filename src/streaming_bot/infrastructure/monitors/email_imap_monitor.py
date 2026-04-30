"""Monitor IMAP generico: red de seguridad redundante.

Lee el inbox configurado y genera ``DistributorAlert`` cuando un email
proviene de un sender de la lista y matchea keywords criticos.

Configuracion via env vars (NO hardcodeadas):
    - ``IMAP_HOST``         (ej. ``imap.gmail.com``)
    - ``IMAP_USER``         email del operador
    - ``IMAP_PASSWORD``     app-password (NO la pass real)
    - ``IMAP_FOLDER``       (default ``INBOX``)

El uso esperado es construir un ``ImapConfig`` desde ``container.py`` con
los valores leidos de ``Settings``.

Tipado: imap-tools NO tiene stubs, por lo que el modulo aparece en el
override ``ignore_missing_imports`` del ``pyproject.toml``. Usamos
``MailMessage`` de forma estructural.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from imap_tools import AND, MailBox
from structlog.stdlib import BoundLogger

from streaming_bot.domain.ports.distributor_monitor import (
    AlertCategory,
    AlertSeverity,
    DistributorAlert,
    DistributorPlatform,
    IDistributorMonitor,
)
from streaming_bot.infrastructure.monitors.base_monitor import (
    KEYWORDS_ACCOUNT_CLOSED,
    KEYWORDS_ACCOUNT_REVIEW,
    KEYWORDS_FILTERED_STREAMS,
    KEYWORDS_PAYMENT_HOLD,
    KEYWORDS_STREAM_MANIPULATION,
)


@dataclass(frozen=True, slots=True)
class ImapConfig:
    """Configuracion IMAP. Cargar desde env vars en ``container.py``."""

    host: str
    user: str
    password: str
    folder: str = "INBOX"
    use_ssl: bool = True
    port: int | None = None  # None -> default IMAP-SSL


# Mapeo platform por dominio del sender (para attribuir alertas).
_PLATFORM_BY_DOMAIN: dict[str, DistributorPlatform] = {
    "distrokid.com": DistributorPlatform.DISTROKID,
    "onerpm.com": DistributorPlatform.ONERPM,
    "aicom.tv": DistributorPlatform.AICOM,
    "spotify.com": DistributorPlatform.SPOTIFY_FOR_ARTISTS,
    "byspotify.com": DistributorPlatform.SPOTIFY_FOR_ARTISTS,
}


@dataclass(slots=True)
class _EmailMatch:
    sender: str
    subject: str
    body: str
    date: datetime


class GenericEmailMonitor(IDistributorMonitor):
    """Monitor IMAP que vigila multiples senders y patrones.

    Implementa ``IDistributorMonitor`` con ``platform = UNKNOWN`` (via
    AICOM como placeholder no es valido; usamos override en cada alerta
    individualmente). Cada alerta se atribuye al ``DistributorPlatform``
    deducido del sender.

    Args:
        config: configuracion IMAP.
        sender_allowlist: lista de emails/dominios a vigilar.
            (ej. ``["support@distrokid.com", "noreply@onerpm.com"]``)
        logger: logger structlog.
        platform: ``DistributorPlatform`` reportada por la property
            ``platform``. Usar la del distribuidor cuya cuenta IMAP se lee,
            o ``DistributorPlatform.AICOM`` si es un inbox compartido y
            queremos un valor por defecto.
        keywords_categories: opcional, override de los pares
            (categoria, keywords).
    """

    def __init__(
        self,
        *,
        config: ImapConfig,
        sender_allowlist: list[str],
        logger: BoundLogger,
        platform: DistributorPlatform = DistributorPlatform.AICOM,
        keywords_categories: list[tuple[AlertCategory, tuple[str, ...]]] | None = None,
    ) -> None:
        self._config = config
        self._allowlist = [s.lower().strip() for s in sender_allowlist if s.strip()]
        self._logger = logger.bind(monitor="generic_email_imap")
        self._platform = platform
        self._categories = keywords_categories or _DEFAULT_CATEGORIES

    @property
    def platform(self) -> DistributorPlatform:
        return self._platform

    async def login_and_scrape(self) -> list[DistributorAlert]:
        """No aplica: este monitor solo lee email. Devuelve lista vacia."""
        return []

    async def is_authenticated(self) -> bool:
        """Verifica que las credenciales IMAP funcionen abriendo la mailbox."""
        return await asyncio.to_thread(self._test_connection)

    async def check_emails(self, since: datetime | None = None) -> list[DistributorAlert]:
        """Lee emails recientes y genera alertas por matches.

        Args:
            since: solo procesar emails con date >= since (UTC). ``None``
                trae los ultimos N (limite imap-tools por defecto ~unread).
        """
        matches = await asyncio.to_thread(self._fetch_matches, since)
        alerts: list[DistributorAlert] = []
        for match in matches:
            alert = self._classify(match)
            if alert is not None:
                alerts.append(alert)
        if alerts:
            self._logger.warning(
                "imap_alerts_detected",
                count=len(alerts),
                platforms=sorted({a.platform.value for a in alerts}),
            )
        return alerts

    # ── Internos ─────────────────────────────────────────────────────────────
    def _test_connection(self) -> bool:
        try:
            with self._open_mailbox() as _:
                return True
        except Exception as exc:
            self._logger.warning("imap_auth_failed", error=str(exc))
            return False

    def _open_mailbox(self) -> Any:
        if self._config.port is not None:
            mailbox = MailBox(self._config.host, port=self._config.port)
        else:
            mailbox = MailBox(self._config.host)
        return mailbox.login(
            self._config.user,
            self._config.password,
            initial_folder=self._config.folder,
        )

    def _fetch_matches(self, since: datetime | None) -> list[_EmailMatch]:
        """I/O bloqueante: extrae emails que matchean allowlist."""
        results: list[_EmailMatch] = []
        try:
            with self._open_mailbox() as mailbox:
                criteria = AND(date_gte=since.date()) if since is not None else AND(all=True)
                # ``mark_seen=False`` para no contaminar el inbox del operador.
                for msg in mailbox.fetch(criteria, mark_seen=False, limit=500):
                    sender = (msg.from_ or "").lower()
                    if not self._sender_in_allowlist(sender):
                        continue
                    msg_date: datetime
                    if msg.date is None:
                        msg_date = datetime.now(UTC)
                    elif msg.date.tzinfo is None:
                        msg_date = msg.date.replace(tzinfo=UTC)
                    else:
                        msg_date = msg.date
                    results.append(
                        _EmailMatch(
                            sender=sender,
                            subject=msg.subject or "",
                            body=(msg.text or msg.html or "")[:10_000],
                            date=msg_date,
                        )
                    )
        except Exception as exc:
            self._logger.warning("imap_fetch_failed", error=str(exc))
        return results

    def _sender_in_allowlist(self, sender: str) -> bool:
        if not self._allowlist:
            return True
        return any(allowed in sender for allowed in self._allowlist)

    def _classify(self, match: _EmailMatch) -> DistributorAlert | None:
        """Asigna categoria/severity al match, si alguna keyword aparece."""
        haystack = f"{match.subject}\n{match.body}".lower()
        for category, keywords in self._categories:
            hits = [kw for kw in keywords if kw.lower() in haystack]
            if not hits:
                continue
            severity = _SEVERITY_BY_CATEGORY.get(category, AlertSeverity.WARNING)
            platform = _platform_for_sender(match.sender, default=self._platform)
            return DistributorAlert(
                platform=platform,
                severity=severity,
                category=category,
                detected_at=match.date,
                message=(f"Email match {category.value} de {match.sender}: {match.subject[:120]}"),
                raw_evidence=(
                    f"FROM: {match.sender}\nSUBJECT: {match.subject}\n\n"
                    f"{match.body[:2_000]}\n\nKEYWORDS: {hits}"
                ),
            )
        return None


# ── Configuracion por defecto del clasificador ────────────────────────────────
_DEFAULT_CATEGORIES: list[tuple[AlertCategory, tuple[str, ...]]] = [
    (AlertCategory.ACCOUNT_CLOSED, KEYWORDS_ACCOUNT_CLOSED),
    (AlertCategory.STREAM_MANIPULATION, KEYWORDS_STREAM_MANIPULATION),
    (AlertCategory.FILTERED_STREAMS, KEYWORDS_FILTERED_STREAMS),
    (AlertCategory.PAYMENT_HOLD, KEYWORDS_PAYMENT_HOLD),
    (AlertCategory.ACCOUNT_REVIEW, KEYWORDS_ACCOUNT_REVIEW),
]

_SEVERITY_BY_CATEGORY: dict[AlertCategory, AlertSeverity] = {
    AlertCategory.ACCOUNT_CLOSED: AlertSeverity.FATAL,
    AlertCategory.STREAM_MANIPULATION: AlertSeverity.CRITICAL,
    AlertCategory.FILTERED_STREAMS: AlertSeverity.CRITICAL,
    AlertCategory.PAYMENT_HOLD: AlertSeverity.CRITICAL,
    AlertCategory.ACCOUNT_REVIEW: AlertSeverity.WARNING,
    AlertCategory.REVENUE_DROP: AlertSeverity.WARNING,
    AlertCategory.SUDDEN_STREAM_DROP: AlertSeverity.WARNING,
    AlertCategory.UNUSUAL_GEO_PATTERN: AlertSeverity.WARNING,
    AlertCategory.UNKNOWN: AlertSeverity.INFO,
}


def _platform_for_sender(sender: str, *, default: DistributorPlatform) -> DistributorPlatform:
    """Deduce el ``DistributorPlatform`` desde el dominio del sender."""
    sender_lc = sender.lower()
    for domain, platform in _PLATFORM_BY_DOMAIN.items():
        if domain in sender_lc:
            return platform
    return default


__all__ = ["GenericEmailMonitor", "ImapConfig"]
