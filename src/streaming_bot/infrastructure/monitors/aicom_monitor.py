"""Monitor stub para aiCom (aicom.tv).

A la fecha de implementacion el equipo no tiene acceso documentado al panel
de aicom.tv para mapear selectores y rutas. Mantenemos este modulo como
placeholder defensivo para que el ``MonitorOrchestrator`` lo invoque sin
romper, hasta que se documente el dashboard.

TODO: una vez se confirmen URLs/selectores:
- Implementar ``login_and_scrape`` similar a ``DistroKidMonitor``.
- Definir keywords especificos del wording de aicom.
- Conectar baseline cache con earnings/stream counts.

Mientras tanto:
- ``login_and_scrape`` devuelve ``[]`` con un log INFO unico al construirse.
- ``check_emails`` reusa el filtro IMAP generico si se inyecta config.
- ``is_authenticated`` devuelve ``True`` (no podemos verificar) -> el
  orchestrator NO debe asumir health real basado en este monitor.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from imap_tools import AND, MailBox
from structlog.stdlib import BoundLogger

from streaming_bot.domain.ports.distributor_monitor import (
    AlertCategory,
    AlertSeverity,
    DistributorAlert,
    DistributorPlatform,
)
from streaming_bot.domain.value_objects import Fingerprint
from streaming_bot.infrastructure.monitors.base_monitor import (
    KEYWORDS_ACCOUNT_CLOSED,
    KEYWORDS_FILTERED_STREAMS,
    KEYWORDS_STREAM_MANIPULATION,
    BaseDistributorMonitor,
)
from streaming_bot.infrastructure.monitors.email_imap_monitor import ImapConfig

if TYPE_CHECKING:
    from streaming_bot.domain.ports.browser_rich import IRichBrowserDriver


class AiComMonitor(BaseDistributorMonitor):
    """Stub para aicom.tv.

    Args:
        browser_driver, fingerprint, storage_state_path, logger:
            ver ``BaseDistributorMonitor``.
        imap_config: opcional, para vigilar emails ``aicom.tv`` aunque el
            dashboard no este mapeado.
    """

    PLATFORM = DistributorPlatform.AICOM

    def __init__(
        self,
        *,
        browser_driver: IRichBrowserDriver,
        fingerprint: Fingerprint,
        storage_state_path: Path,
        logger: BoundLogger,
        imap_config: ImapConfig | None = None,
    ) -> None:
        super().__init__(
            browser_driver=browser_driver,
            fingerprint=fingerprint,
            storage_state_path=storage_state_path,
            logger=logger,
        )
        self._imap_config = imap_config
        self._logger.info(
            "aicom_monitor_stub_active",
            note="Dashboard scraping no implementado; solo IMAP fallback",
        )

    async def login_and_scrape(self) -> list[DistributorAlert]:
        # TODO: implementar cuando se documente el panel de aicom.tv.
        return []

    async def check_emails(self, since: datetime | None = None) -> list[DistributorAlert]:
        if self._imap_config is None:
            return []
        return await asyncio.to_thread(self._fetch_emails_blocking, since)

    def _fetch_emails_blocking(self, since: datetime | None) -> list[DistributorAlert]:
        config = self._imap_config
        if config is None:
            return []
        alerts: list[DistributorAlert] = []
        try:
            with MailBox(config.host).login(
                config.user, config.password, initial_folder=config.folder
            ) as mailbox:
                criteria = (
                    AND(date_gte=since.date(), from_="aicom.tv") if since else AND(from_="aicom.tv")
                )
                for msg in mailbox.fetch(criteria, mark_seen=False, limit=200):
                    haystack = f"{msg.subject or ''}\n{msg.text or msg.html or ''}"
                    when = (
                        msg.date.replace(tzinfo=UTC)
                        if msg.date and msg.date.tzinfo is None
                        else (msg.date or datetime.now(UTC))
                    )
                    if self._match_keywords(haystack, KEYWORDS_ACCOUNT_CLOSED):
                        alerts.append(
                            DistributorAlert(
                                platform=self.PLATFORM,
                                severity=AlertSeverity.FATAL,
                                category=AlertCategory.ACCOUNT_CLOSED,
                                detected_at=when,
                                message="aiCom email: cuenta cerrada",
                                raw_evidence=haystack[:2_000],
                            )
                        )
                        continue
                    if self._match_keywords(haystack, KEYWORDS_STREAM_MANIPULATION):
                        alerts.append(
                            DistributorAlert(
                                platform=self.PLATFORM,
                                severity=AlertSeverity.CRITICAL,
                                category=AlertCategory.STREAM_MANIPULATION,
                                detected_at=when,
                                message="aiCom email: stream manipulation",
                                raw_evidence=haystack[:2_000],
                            )
                        )
                        continue
                    if self._match_keywords(haystack, KEYWORDS_FILTERED_STREAMS):
                        alerts.append(
                            DistributorAlert(
                                platform=self.PLATFORM,
                                severity=AlertSeverity.CRITICAL,
                                category=AlertCategory.FILTERED_STREAMS,
                                detected_at=when,
                                message="aiCom email: streams filtrados",
                                raw_evidence=haystack[:2_000],
                            )
                        )
        except Exception as exc:
            self._logger.warning("aicom_imap_fetch_failed", error=str(exc))
        return alerts

    async def is_authenticated(self) -> bool:
        # No podemos verificar sin URL del panel; devolvemos True para no
        # bloquear orchestrator. El equipo debe implementar esto pronto.
        self._logger.debug("aicom_is_authenticated_stub_true")
        return True
