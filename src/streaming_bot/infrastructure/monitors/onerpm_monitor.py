"""Monitor scraping de OneRPM.

Estrategia mixta:
1. Intento `httpx` directo a la API privada (``app.onerpm.com/api/...``)
   con cookies extraidas del browser context. Si responde 200 con JSON,
   parseamos earnings/streams sin browser overhead.
2. Si la API no responde o cambia, fallback a scraping del DOM con selectolax.

Esto reduce el ruido en logs y mejora la deteccion temprana cuando
OneRPM rota su frontend pero mantiene la API.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from imap_tools import AND, MailBox
from structlog.stdlib import BoundLogger
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

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


ONERPM_BASE = "https://app.onerpm.com"
ONERPM_DASHBOARD = f"{ONERPM_BASE}/dashboard"
ONERPM_EARNINGS = f"{ONERPM_BASE}/earnings"
ONERPM_SIGNIN = f"{ONERPM_BASE}/login"
ONERPM_API_EARNINGS = f"{ONERPM_BASE}/api/v1/earnings/summary"

_SELECTOR_BANNERS = (
    ".alert, .notice, .warning, [role='alert'], "
    "[class*='banner'], [class*='warning'], [class*='alert']"
)
_SELECTOR_LOGIN_FORM = "form[action*='login'], input[type='password']"
_SELECTOR_EARNINGS_AMOUNT = (
    "[data-testid*='earnings-total'], [data-cy*='earnings-total'], .earnings-total, .total-amount"
)
_SELECTOR_EARNINGS_ROW = "table tr, .earnings-row"


class OneRPMMonitor(BaseDistributorMonitor):
    """Monitor para OneRPM.

    Args:
        browser_driver, fingerprint, storage_state_path, logger:
            ver ``BaseDistributorMonitor``.
        baseline_cache: cache de baselines.
        http_client: cliente httpx async (se cierra fuera). Inyectable por
            tests para evitar I/O real.
        imap_config: opcional para emails de soporte.
        revenue_drop_threshold_pct: umbral porcentual.
    """

    PLATFORM = DistributorPlatform.ONERPM

    def __init__(
        self,
        *,
        browser_driver: IRichBrowserDriver,
        fingerprint: Fingerprint,
        storage_state_path: Path,
        logger: BoundLogger,
        baseline_cache: BaselineCache,
        http_client: httpx.AsyncClient | None = None,
        imap_config: ImapConfig | None = None,
        revenue_drop_threshold_pct: float = DEFAULT_REVENUE_DROP_THRESHOLD_PCT,
    ) -> None:
        super().__init__(
            browser_driver=browser_driver,
            fingerprint=fingerprint,
            storage_state_path=storage_state_path,
            logger=logger,
        )
        self._baseline_cache = baseline_cache
        self._http_client = http_client
        self._imap_config = imap_config
        self._revenue_threshold = revenue_drop_threshold_pct

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
                    raise AuthenticationError("OneRPM: sesion invalida")

                dashboard_html = await self._safe_goto(session, ONERPM_DASHBOARD)
                alerts.extend(self.scan_dashboard_html(dashboard_html))

                earnings_html = await self._safe_goto(session, ONERPM_EARNINGS)
                fresh_state = await session.storage_state()
                self._save_storage_state(fresh_state)

                # Intento API privada (mas robusto que parsear DOM).
                api_total = await self._try_fetch_api_earnings(fresh_state)
                if api_total is not None:
                    alerts.extend(self._evaluate_earnings_total(api_total))
                else:
                    alerts.extend(self.scan_earnings_html(earnings_html))
        except AuthenticationError:
            alerts.append(
                self._build_alert(
                    severity=AlertSeverity.WARNING,
                    category=AlertCategory.UNKNOWN,
                    message="OneRPM: sesion expirada, no se pudo scrapear",
                )
            )
        except TargetSiteError as exc:
            self._logger.warning("onerpm_target_site_error", error=str(exc))
        return alerts

    async def _verify_session(self, session: IRichBrowserSession) -> bool:
        try:
            await session.goto(ONERPM_DASHBOARD, wait_until="domcontentloaded")
        except TargetSiteError:
            return False
        url = await session.current_url()
        if "/login" in url.lower():
            return False
        return not await session.is_visible(_SELECTOR_LOGIN_FORM, timeout_ms=1500)

    async def _safe_goto(self, session: IRichBrowserSession, url: str) -> str:
        try:
            await session.goto(url, wait_until="domcontentloaded")
            await session.wait(800)
            return await session.content()
        except TargetSiteError as exc:
            self._logger.warning("onerpm_navigation_failed", url=url, error=str(exc))
            return ""

    # ── HTTP API ─────────────────────────────────────────────────────────────
    async def _try_fetch_api_earnings(self, storage_state: dict[str, Any]) -> float | None:
        """Intenta llamar la API privada con cookies del storage_state."""
        if self._http_client is None:
            return None

        cookies = _cookies_from_storage_state(storage_state, domain="onerpm.com")
        if not cookies:
            return None

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(min=0.5, max=4),
                retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
                reraise=True,
            ):
                with attempt:
                    response = await self._http_client.get(
                        ONERPM_API_EARNINGS,
                        cookies=cookies,
                        headers={
                            "Accept": "application/json",
                            "User-Agent": self._fingerprint.user_agent,
                        },
                        timeout=8.0,
                    )
                    if response.status_code in {401, 403}:
                        # Sesion no valida via API; sin reintentos.
                        return None
                    response.raise_for_status()
                    payload = response.json()
                    return _extract_total_from_api_payload(payload)
        except (RetryError, httpx.HTTPError, ValueError) as exc:
            self._logger.info("onerpm_api_fallback_to_dom", error=str(exc))
            return None
        return None

    # ── Analizadores HTML (puros) ────────────────────────────────────────────
    def scan_dashboard_html(self, html: str) -> list[DistributorAlert]:
        if not html:
            return []
        alerts: list[DistributorAlert] = []
        banners = self._extract_all_texts(html, _SELECTOR_BANNERS)
        body = self._extract_text(html, "body") or ""

        for text in [*banners, body]:
            if not text:
                continue
            if self._match_keywords(text, KEYWORDS_ACCOUNT_CLOSED):
                alerts.append(
                    self._build_alert(
                        severity=AlertSeverity.FATAL,
                        category=AlertCategory.ACCOUNT_CLOSED,
                        message="OneRPM: cuenta cerrada",
                        evidence=text,
                    )
                )
                break
            if self._match_keywords(text, KEYWORDS_STREAM_MANIPULATION):
                alerts.append(
                    self._build_alert(
                        severity=AlertSeverity.CRITICAL,
                        category=AlertCategory.STREAM_MANIPULATION,
                        message="OneRPM: warning de manipulacion",
                        evidence=text,
                    )
                )
            if self._match_keywords(text, KEYWORDS_FILTERED_STREAMS):
                alerts.append(
                    self._build_alert(
                        severity=AlertSeverity.CRITICAL,
                        category=AlertCategory.FILTERED_STREAMS,
                        message="OneRPM: streams filtrados",
                        evidence=text,
                    )
                )
            if self._match_keywords(text, KEYWORDS_PAYMENT_HOLD):
                alerts.append(
                    self._build_alert(
                        severity=AlertSeverity.CRITICAL,
                        category=AlertCategory.PAYMENT_HOLD,
                        message="OneRPM: pagos retenidos",
                        evidence=text,
                    )
                )
            if self._match_keywords(text, KEYWORDS_ACCOUNT_REVIEW):
                alerts.append(
                    self._build_alert(
                        severity=AlertSeverity.WARNING,
                        category=AlertCategory.ACCOUNT_REVIEW,
                        message="OneRPM: cuenta bajo revision",
                        evidence=text,
                    )
                )
        return _dedupe(alerts)

    def scan_earnings_html(self, html: str) -> list[DistributorAlert]:
        if not html:
            return []
        # Intentamos primero el indicador grande; si no, sumamos filas.
        amount_text = self._extract_text(html, _SELECTOR_EARNINGS_AMOUNT)
        total: float | None = None
        if amount_text:
            total = self._parse_money_value(amount_text)
        if total is None:
            rows = self._extract_all_texts(html, _SELECTOR_EARNINGS_ROW)
            running = 0.0
            for row in rows:
                value = self._parse_money_value(row)
                if value is not None and value > 0:
                    running += value
            total = running if running > 0 else None

        if total is None or total <= 0:
            return []
        return self._evaluate_earnings_total(total)

    def _evaluate_earnings_total(self, total: float) -> list[DistributorAlert]:
        delta = self._baseline_cache.compute_delta_pct(
            DistributorPlatform.ONERPM,
            "earnings_monthly",
            current_value=total,
        )
        self._baseline_cache.record_metric(DistributorPlatform.ONERPM, "earnings_monthly", total)
        if delta is None:
            return []
        if delta <= self._revenue_threshold:
            return [
                self._build_alert(
                    severity=AlertSeverity.CRITICAL,
                    category=AlertCategory.REVENUE_DROP,
                    message=(
                        f"OneRPM: earnings cayeron {delta:.1f}% "
                        f"(umbral {self._revenue_threshold:.0f}%)"
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
        config = self._imap_config
        if config is None:
            return []
        alerts: list[DistributorAlert] = []
        try:
            with MailBox(config.host).login(
                config.user, config.password, initial_folder=config.folder
            ) as mailbox:
                criteria = (
                    AND(date_gte=since.date(), from_="onerpm.com")
                    if since
                    else AND(from_="onerpm.com")
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
                                message="OneRPM email: cuenta cerrada",
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
                                message="OneRPM email: stream manipulation",
                                raw_evidence=haystack[:2_000],
                            )
                        )
        except Exception as exc:
            self._logger.warning("onerpm_imap_fetch_failed", error=str(exc))
        return alerts

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
                    await session.goto(ONERPM_SIGNIN, wait_until="domcontentloaded")
                except TargetSiteError:
                    return False
                url = await session.current_url()
                if "/login" not in url.lower():
                    return True
                login_visible = await session.is_visible(_SELECTOR_LOGIN_FORM, timeout_ms=1500)
                return not login_visible
        except Exception as exc:
            self._logger.warning("onerpm_is_authenticated_failed", error=str(exc))
            return False


# ── Helpers privados al modulo ────────────────────────────────────────────────
def _cookies_from_storage_state(
    storage_state: dict[str, Any] | None, *, domain: str
) -> dict[str, str]:
    """Extrae cookies de storage_state filtrando por dominio."""
    if not storage_state:
        return {}
    cookies_raw = storage_state.get("cookies", []) if isinstance(storage_state, dict) else []
    if not isinstance(cookies_raw, list):
        return {}
    out: dict[str, str] = {}
    for c in cookies_raw:
        if not isinstance(c, dict):
            continue
        d = str(c.get("domain", ""))
        if domain not in d:
            continue
        name = c.get("name")
        value = c.get("value")
        if isinstance(name, str) and isinstance(value, str):
            out[name] = value
    return out


def _extract_total_from_api_payload(payload: Any) -> float | None:
    """Tolerante a varios shapes: ``{total: 123.45}``, ``{data: {total_usd: 123}}``."""
    if not isinstance(payload, dict):
        return None
    for key in ("total", "total_usd", "amount", "earnings_total"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_total_from_api_payload(data)
    return None


def _dedupe(alerts: list[DistributorAlert]) -> list[DistributorAlert]:
    seen: set[tuple[str, str, str]] = set()
    out: list[DistributorAlert] = []
    for alert in alerts:
        key = (alert.severity.value, alert.category.value, alert.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(alert)
    return out
