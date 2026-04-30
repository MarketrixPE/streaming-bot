"""Monitor scraping de DistroKid.

Rutas vigiladas:
- ``/dashboard``      -> banners "Account under review", "Stream Banker".
- ``/mybank/`` o ``/earnings/`` -> tabla de earnings; alimenta baseline cache.
- ``/myaccount/``     -> mensajes de soporte/violations.
- IMAP del operador   -> emails de ``support@distrokid.com``.

Dado que el dashboard exacto puede cambiar, se asumen selectores defensivos
y se confia primero en los textos visibles del DOM matcheados contra los
diccionarios ``KEYWORDS_*`` de ``base_monitor.py``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from imap_tools import AND, MailBox
from structlog.stdlib import BoundLogger

from streaming_bot.domain.exceptions import (
    AuthenticationError,
    TargetSiteError,
)
from streaming_bot.domain.ports.browser_rich import IRichBrowserDriver
from streaming_bot.domain.ports.distributor_monitor import (
    AlertCategory,
    AlertSeverity,
    DistributorAlert,
    DistributorPlatform,
)
from streaming_bot.domain.value_objects import Fingerprint
from streaming_bot.infrastructure.monitors.base_monitor import (
    DEFAULT_REVENUE_DROP_THRESHOLD_PCT,
    KEYWORDS_ACCOUNT_CLOSED,
    KEYWORDS_ACCOUNT_REVIEW,
    KEYWORDS_FILTERED_STREAMS,
    KEYWORDS_PAYMENT_HOLD,
    KEYWORDS_STREAM_MANIPULATION,
    BaseDistributorMonitor,
)
from streaming_bot.infrastructure.monitors.baseline_cache import BaselineCache
from streaming_bot.infrastructure.monitors.email_imap_monitor import ImapConfig

if TYPE_CHECKING:
    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession


DISTROKID_BASE = "https://distrokid.com"
DISTROKID_DASHBOARD = f"{DISTROKID_BASE}/dashboard/"
DISTROKID_BANK = f"{DISTROKID_BASE}/mybank/"
DISTROKID_ACCOUNT = f"{DISTROKID_BASE}/myaccount/"
DISTROKID_SIGNIN = f"{DISTROKID_BASE}/signin/"

# Selectores defensivos. Usamos data-attrs si DistroKid los expone, sino divs.
_SELECTOR_BANNERS = (
    ".alert, .banner, .notice, .warning, [role='alert'], [data-testid*='warning'], [class*='alert']"
)
_SELECTOR_LOGIN_FORM = "form[action*='signin'], input[name='email'][type='email']"
_SELECTOR_EARNINGS_ROW = "table tr, .earnings-row, [data-row='earnings']"


class DistroKidMonitor(BaseDistributorMonitor):
    """Monitor para DistroKid.

    Args:
        browser_driver: driver rico (``IRichBrowserDriver``).
        fingerprint: huella coherente.
        storage_state_path: archivo JSON para sesion persistida.
        logger: logger structlog.
        baseline_cache: cache para deteccion de caidas mes-mes en earnings.
        imap_config: configuracion IMAP para revisar emails (opcional).
        revenue_drop_threshold_pct: umbral porcentual negativo (default -40).
        artist_id: opcional, para anotar logs/alertas.
    """

    PLATFORM = DistributorPlatform.DISTROKID

    def __init__(
        self,
        *,
        browser_driver: IRichBrowserDriver,
        fingerprint: Fingerprint,
        storage_state_path: Path,
        logger: BoundLogger,
        baseline_cache: BaselineCache,
        imap_config: ImapConfig | None = None,
        revenue_drop_threshold_pct: float = DEFAULT_REVENUE_DROP_THRESHOLD_PCT,
        artist_id: str | None = None,
    ) -> None:
        super().__init__(
            browser_driver=browser_driver,
            fingerprint=fingerprint,
            storage_state_path=storage_state_path,
            logger=logger,
        )
        self._baseline_cache = baseline_cache
        self._imap_config = imap_config
        self._revenue_threshold = revenue_drop_threshold_pct
        self._artist_id = artist_id

    # ── Scraping del dashboard ───────────────────────────────────────────────
    async def login_and_scrape(self) -> list[DistributorAlert]:
        storage_state = self._load_storage_state()
        alerts: list[DistributorAlert] = []
        try:
            async with self._browser_driver.session(
                proxy=None,
                fingerprint=self._fingerprint,
                storage_state=storage_state,
            ) as session:
                if not await self._verify_session(session):
                    raise AuthenticationError(
                        "DistroKid: sesion invalida; requiere re-login manual"
                    )

                dashboard_html = await self._safe_goto(session, DISTROKID_DASHBOARD)
                alerts.extend(self.scan_dashboard_html(dashboard_html))

                bank_html = await self._safe_goto(session, DISTROKID_BANK)
                alerts.extend(self.scan_earnings_html(bank_html))

                account_html = await self._safe_goto(session, DISTROKID_ACCOUNT)
                alerts.extend(self.scan_dashboard_html(account_html))

                # Persistimos la sesion fresca al storage_state.
                fresh_state = await session.storage_state()
                self._save_storage_state(fresh_state)
        except AuthenticationError:
            alerts.append(
                self._build_alert(
                    severity=AlertSeverity.WARNING,
                    category=AlertCategory.UNKNOWN,
                    message="DistroKid: sesion expirada, no se pudo scrapear",
                )
            )
        except TargetSiteError as exc:
            self._logger.warning("distrokid_target_site_error", error=str(exc))
        return alerts

    async def _verify_session(self, session: IRichBrowserSession) -> bool:
        try:
            await session.goto(DISTROKID_DASHBOARD, wait_until="domcontentloaded")
        except TargetSiteError:
            return False
        url = await session.current_url()
        if "/signin" in url.lower():
            return False
        return not await session.is_visible(_SELECTOR_LOGIN_FORM, timeout_ms=1500)

    async def _safe_goto(self, session: IRichBrowserSession, url: str) -> str:
        try:
            await session.goto(url, wait_until="domcontentloaded")
            await session.wait(800)
            return await session.content()
        except TargetSiteError as exc:
            self._logger.warning("distrokid_navigation_failed", url=url, error=str(exc))
            return ""

    # ── Analizadores HTML (puros, testeables sin browser) ────────────────────
    def scan_dashboard_html(self, html: str) -> list[DistributorAlert]:
        """Scan defensivo del HTML del dashboard buscando banners/warnings."""
        if not html:
            return []
        alerts: list[DistributorAlert] = []
        banners = self._extract_all_texts(html, _SELECTOR_BANNERS)
        # Tambien analizamos el cuerpo entero como red ultima.
        body_text = self._extract_text(html, "body") or ""

        candidate_texts = [*banners, body_text]

        for text in candidate_texts:
            if not text:
                continue
            if self._match_keywords(text, KEYWORDS_ACCOUNT_CLOSED):
                alerts.append(
                    self._build_alert(
                        severity=AlertSeverity.FATAL,
                        category=AlertCategory.ACCOUNT_CLOSED,
                        message="DistroKid: cuenta cerrada/terminada detectada",
                        evidence=text,
                    )
                )
                break
            if self._match_keywords(text, KEYWORDS_STREAM_MANIPULATION):
                alerts.append(
                    self._build_alert(
                        severity=AlertSeverity.CRITICAL,
                        category=AlertCategory.STREAM_MANIPULATION,
                        message="DistroKid: warning de stream manipulation",
                        evidence=text,
                    )
                )
            if self._match_keywords(text, KEYWORDS_FILTERED_STREAMS):
                alerts.append(
                    self._build_alert(
                        severity=AlertSeverity.CRITICAL,
                        category=AlertCategory.FILTERED_STREAMS,
                        message="DistroKid: streams filtrados reportados",
                        evidence=text,
                    )
                )
            if self._match_keywords(text, KEYWORDS_PAYMENT_HOLD):
                alerts.append(
                    self._build_alert(
                        severity=AlertSeverity.CRITICAL,
                        category=AlertCategory.PAYMENT_HOLD,
                        message="DistroKid: pagos retenidos",
                        evidence=text,
                    )
                )
            if self._match_keywords(text, KEYWORDS_ACCOUNT_REVIEW):
                alerts.append(
                    self._build_alert(
                        severity=AlertSeverity.WARNING,
                        category=AlertCategory.ACCOUNT_REVIEW,
                        message="DistroKid: cuenta bajo revision manual",
                        evidence=text,
                    )
                )
        return _dedupe_alerts(alerts)

    def scan_earnings_html(self, html: str) -> list[DistributorAlert]:
        """Suma earnings visibles, los registra en baseline y emite alerta
        si la caida vs mediana de meses previos supera el umbral.
        """
        if not html:
            return []
        rows = self._extract_all_texts(html, _SELECTOR_EARNINGS_ROW)
        total = 0.0
        for row in rows:
            value = self._parse_money_value(row)
            if value is not None and value > 0:
                total += value

        if total <= 0:
            self._logger.info("distrokid_earnings_zero_or_unparseable")
            return []

        delta = self._baseline_cache.compute_delta_pct(
            DistributorPlatform.DISTROKID,
            "earnings_monthly",
            current_value=total,
        )
        # Persistimos la muestra ANTES de evaluar para mantener historico.
        self._baseline_cache.record_metric(
            DistributorPlatform.DISTROKID,
            "earnings_monthly",
            total,
        )

        if delta is None:
            return []

        if delta <= self._revenue_threshold:
            return [
                self._build_alert(
                    severity=AlertSeverity.CRITICAL,
                    category=AlertCategory.REVENUE_DROP,
                    message=(
                        f"DistroKid: earnings cayeron {delta:.1f}% "
                        f"vs mediana historica (umbral {self._revenue_threshold:.0f}%)"
                    ),
                    evidence=f"current_total={total:.2f}",
                )
            ]
        return []

    # ── IMAP ────────────────────────────────────────────────────────────────
    async def check_emails(self, since: datetime | None = None) -> list[DistributorAlert]:
        if self._imap_config is None:
            return []
        return await asyncio.to_thread(self._fetch_emails_blocking, since)

    def _fetch_emails_blocking(self, since: datetime | None) -> list[DistributorAlert]:
        """I/O IMAP bloqueante. Llamar via ``asyncio.to_thread``."""
        config = self._imap_config
        if config is None:  # pragma: no cover - garantia de tipo
            return []
        alerts: list[DistributorAlert] = []
        try:
            with MailBox(config.host).login(
                config.user, config.password, initial_folder=config.folder
            ) as mailbox:
                criteria = (
                    AND(date_gte=since.date(), from_="distrokid.com")
                    if since
                    else AND(from_="distrokid.com")
                )
                for msg in mailbox.fetch(criteria, mark_seen=False, limit=200):
                    haystack = f"{msg.subject or ''}\n{msg.text or msg.html or ''}"
                    msg_date = self._normalize_date(msg.date)
                    alert = self._classify_email(haystack, msg.subject or "", msg_date)
                    if alert is not None:
                        alerts.append(alert)
        except Exception as exc:
            self._logger.warning("distrokid_imap_fetch_failed", error=str(exc))
        return alerts

    @staticmethod
    def _normalize_date(date: datetime | None) -> datetime:
        if date is None:
            return datetime.now(UTC)
        if date.tzinfo is None:
            return date.replace(tzinfo=UTC)
        return date

    def _classify_email(self, body: str, subject: str, when: datetime) -> DistributorAlert | None:
        text = body.lower()
        message_prefix = f"DistroKid email '{subject[:80]}'"
        if self._match_keywords(text, KEYWORDS_ACCOUNT_CLOSED):
            return DistributorAlert(
                platform=self.PLATFORM,
                severity=AlertSeverity.FATAL,
                category=AlertCategory.ACCOUNT_CLOSED,
                detected_at=when,
                message=f"{message_prefix}: cuenta cerrada",
                raw_evidence=body[:2_000],
            )
        if self._match_keywords(text, KEYWORDS_STREAM_MANIPULATION):
            return DistributorAlert(
                platform=self.PLATFORM,
                severity=AlertSeverity.CRITICAL,
                category=AlertCategory.STREAM_MANIPULATION,
                detected_at=when,
                message=f"{message_prefix}: stream manipulation",
                raw_evidence=body[:2_000],
            )
        if self._match_keywords(text, KEYWORDS_FILTERED_STREAMS):
            return DistributorAlert(
                platform=self.PLATFORM,
                severity=AlertSeverity.CRITICAL,
                category=AlertCategory.FILTERED_STREAMS,
                detected_at=when,
                message=f"{message_prefix}: streams filtrados",
                raw_evidence=body[:2_000],
            )
        if self._match_keywords(text, KEYWORDS_PAYMENT_HOLD):
            return DistributorAlert(
                platform=self.PLATFORM,
                severity=AlertSeverity.CRITICAL,
                category=AlertCategory.PAYMENT_HOLD,
                detected_at=when,
                message=f"{message_prefix}: pagos retenidos",
                raw_evidence=body[:2_000],
            )
        if self._match_keywords(text, KEYWORDS_ACCOUNT_REVIEW):
            return DistributorAlert(
                platform=self.PLATFORM,
                severity=AlertSeverity.WARNING,
                category=AlertCategory.ACCOUNT_REVIEW,
                detected_at=when,
                message=f"{message_prefix}: cuenta bajo revision",
                raw_evidence=body[:2_000],
            )
        return None

    # ── is_authenticated ─────────────────────────────────────────────────────
    async def is_authenticated(self) -> bool:
        storage_state = self._load_storage_state()
        try:
            async with self._browser_driver.session(
                proxy=None,
                fingerprint=self._fingerprint,
                storage_state=storage_state,
            ) as session:
                try:
                    await session.goto(DISTROKID_SIGNIN, wait_until="domcontentloaded")
                except TargetSiteError:
                    return False
                url = await session.current_url()
                if "/signin" not in url.lower():
                    # DistroKid suele redirigir a dashboard si ya estas logado.
                    return True
                # Si el form de login es visible -> NO autenticado.
                login_visible = await session.is_visible(_SELECTOR_LOGIN_FORM, timeout_ms=1500)
                return not login_visible
        except Exception as exc:
            self._logger.warning("distrokid_is_authenticated_failed", error=str(exc))
            return False


# ── Helpers privados al modulo ────────────────────────────────────────────────
def _dedupe_alerts(alerts: list[DistributorAlert]) -> list[DistributorAlert]:
    """Deduplica alertas identicas por (severity, category, message)."""
    seen: set[tuple[str, str, str]] = set()
    out: list[DistributorAlert] = []
    for alert in alerts:
        key = (alert.severity.value, alert.category.value, alert.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(alert)
    return out
