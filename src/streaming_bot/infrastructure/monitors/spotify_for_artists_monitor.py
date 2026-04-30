"""Monitor scraping de Spotify for Artists (artists.spotify.com).

ESTE ES EL MONITOR MAS CRITICO: Spotify es la fuente de verdad. Cualquier
flag aqui dispara kill-switch INMEDIATAMENTE.

Senales monitoreadas:
1. Banner "Some streams may have been filtered" (filtered streams).
2. Streams en los ultimos 28 dias vs baseline -> caida >30% = sudden drop.
3. Monthly listeners vs baseline -> caida >30% = revenue/audience drop.
4. Notificaciones en /home con keywords de manipulation.
5. Emails de ``no-reply@spotify.com`` / ``help@spotify.com``.

Detalle: artists.spotify.com expone vistas como ``/artist/{id}/stats``,
``/artist/{id}/audience`` y un panel global ``/c/dashboard``. Usamos
``IRichBrowserSession`` con storage_state persistido.
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
    DEFAULT_LISTENERS_DROP_THRESHOLD_PCT,
    KEYWORDS_ACCOUNT_CLOSED,
    KEYWORDS_ACCOUNT_REVIEW,
    KEYWORDS_FILTERED_STREAMS,
    KEYWORDS_STREAM_MANIPULATION,
    BaseDistributorMonitor,
)
from streaming_bot.infrastructure.monitors.baseline_cache import BaselineCache
from streaming_bot.infrastructure.monitors.email_imap_monitor import ImapConfig

if TYPE_CHECKING:
    from streaming_bot.domain.ports.browser_rich import IRichBrowserSession


S4A_BASE = "https://artists.spotify.com"
S4A_LOGIN = f"{S4A_BASE}/login"


def _stats_url(artist_id: str) -> str:
    return f"{S4A_BASE}/c/artist/{artist_id}/stats"


def _audience_url(artist_id: str) -> str:
    return f"{S4A_BASE}/c/artist/{artist_id}/audience"


def _home_url(artist_id: str) -> str:
    return f"{S4A_BASE}/c/artist/{artist_id}/home"


_SELECTOR_BANNERS = (
    "[role='alert'], .Banner, [data-testid*='banner'], "
    "[data-testid*='warning'], [class*='Notification'], "
    ".alert, [class*='Alert']"
)
_SELECTOR_STREAMS_28D = (
    "[data-testid='streams-28-day'] [data-testid='value'], "
    "[data-testid='streams-stat'] strong, "
    "[data-testid*='streams'] [data-testid='value']"
)
_SELECTOR_LISTENERS = (
    "[data-testid='monthly-listeners'] [data-testid='value'], "
    "[data-testid='listeners-stat'] strong, "
    "[data-testid*='listeners'] [data-testid='value']"
)
_SELECTOR_LOGIN_FORM = "form#login-form, input[name='username'], input#login-username"


class SpotifyForArtistsMonitor(BaseDistributorMonitor):
    """Monitor critico para artists.spotify.com.

    Args:
        browser_driver, fingerprint, storage_state_path, logger:
            ver ``BaseDistributorMonitor``.
        baseline_cache: cache para deltas de streams/listeners.
        artist_id: ID del artista a vigilar (obligatorio).
        imap_config: opcional para emails de Spotify.
        listeners_drop_threshold_pct: umbral negativo (default -30).
        streams_drop_threshold_pct: umbral negativo (default -30).
    """

    PLATFORM = DistributorPlatform.SPOTIFY_FOR_ARTISTS

    def __init__(
        self,
        *,
        browser_driver: IRichBrowserDriver,
        fingerprint: Fingerprint,
        storage_state_path: Path,
        logger: BoundLogger,
        baseline_cache: BaselineCache,
        artist_id: str,
        imap_config: ImapConfig | None = None,
        listeners_drop_threshold_pct: float = DEFAULT_LISTENERS_DROP_THRESHOLD_PCT,
        streams_drop_threshold_pct: float = DEFAULT_LISTENERS_DROP_THRESHOLD_PCT,
    ) -> None:
        super().__init__(
            browser_driver=browser_driver,
            fingerprint=fingerprint,
            storage_state_path=storage_state_path,
            logger=logger,
        )
        if not artist_id:
            raise ValueError("artist_id obligatorio para SpotifyForArtistsMonitor")
        self._baseline_cache = baseline_cache
        self._artist_id = artist_id
        self._imap_config = imap_config
        self._listeners_threshold = listeners_drop_threshold_pct
        self._streams_threshold = streams_drop_threshold_pct

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
                    raise AuthenticationError("S4A: sesion invalida; requiere re-login manual")

                home_html = await self._safe_goto(session, _home_url(self._artist_id))
                alerts.extend(self.scan_notifications_html(home_html))

                stats_html = await self._safe_goto(session, _stats_url(self._artist_id))
                alerts.extend(self.scan_stats_html(stats_html))

                audience_html = await self._safe_goto(session, _audience_url(self._artist_id))
                alerts.extend(self.scan_audience_html(audience_html))

                fresh_state = await session.storage_state()
                self._save_storage_state(fresh_state)
        except AuthenticationError:
            alerts.append(
                self._build_alert(
                    severity=AlertSeverity.WARNING,
                    category=AlertCategory.UNKNOWN,
                    message="S4A: sesion expirada, no se pudo scrapear",
                )
            )
        except TargetSiteError as exc:
            self._logger.warning("s4a_target_site_error", error=str(exc))
        return alerts

    async def _verify_session(self, session: IRichBrowserSession) -> bool:
        try:
            await session.goto(_home_url(self._artist_id), wait_until="domcontentloaded")
        except TargetSiteError:
            return False
        url = await session.current_url()
        if "/login" in url.lower() or "accounts.spotify.com" in url.lower():
            return False
        return not await session.is_visible(_SELECTOR_LOGIN_FORM, timeout_ms=1500)

    async def _safe_goto(self, session: IRichBrowserSession, url: str) -> str:
        try:
            await session.goto(url, wait_until="domcontentloaded")
            await session.wait(1200)
            return await session.content()
        except TargetSiteError as exc:
            self._logger.warning("s4a_navigation_failed", url=url, error=str(exc))
            return ""

    # ── Analizadores HTML (puros, testeables) ────────────────────────────────
    def scan_notifications_html(self, html: str) -> list[DistributorAlert]:
        """Banners/notificaciones en home. Spotify usa wording sutil."""
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
                        message="S4A: cuenta cerrada/baneada por Spotify",
                        evidence=text,
                    )
                )
                break
            if self._match_keywords(text, KEYWORDS_FILTERED_STREAMS):
                alerts.append(
                    self._build_alert(
                        severity=AlertSeverity.CRITICAL,
                        category=AlertCategory.FILTERED_STREAMS,
                        message="S4A: Spotify filtro streams (anti-fraud)",
                        evidence=text,
                    )
                )
            if self._match_keywords(text, KEYWORDS_STREAM_MANIPULATION):
                alerts.append(
                    self._build_alert(
                        severity=AlertSeverity.CRITICAL,
                        category=AlertCategory.STREAM_MANIPULATION,
                        message="S4A: warning de stream manipulation",
                        evidence=text,
                    )
                )
            if self._match_keywords(text, KEYWORDS_ACCOUNT_REVIEW):
                alerts.append(
                    self._build_alert(
                        severity=AlertSeverity.WARNING,
                        category=AlertCategory.ACCOUNT_REVIEW,
                        message="S4A: cuenta bajo revision",
                        evidence=text,
                    )
                )
        return _dedupe(alerts)

    def scan_stats_html(self, html: str) -> list[DistributorAlert]:
        """Compara streams 28d vs baseline. Genera alertas por caida."""
        if not html:
            return []
        alerts: list[DistributorAlert] = []
        # 1. Banners en la pagina de stats.
        alerts.extend(self.scan_notifications_html(html))

        # 2. Numero de streams 28d.
        streams_text = self._extract_text(html, _SELECTOR_STREAMS_28D)
        streams_value = self._parse_int_value(streams_text) if streams_text else None
        if streams_value is not None and streams_value >= 0:
            delta = self._baseline_cache.compute_delta_pct(
                DistributorPlatform.SPOTIFY_FOR_ARTISTS,
                "streams_28d",
                current_value=float(streams_value),
            )
            self._baseline_cache.record_metric(
                DistributorPlatform.SPOTIFY_FOR_ARTISTS,
                "streams_28d",
                float(streams_value),
            )
            if delta is not None and delta <= self._streams_threshold:
                alerts.append(
                    self._build_alert(
                        severity=AlertSeverity.CRITICAL,
                        category=AlertCategory.SUDDEN_STREAM_DROP,
                        message=(
                            f"S4A: streams 28d cayeron {delta:.1f}% "
                            f"(umbral {self._streams_threshold:.0f}%)"
                        ),
                        evidence=f"streams_28d={streams_value}",
                    )
                )
        return _dedupe(alerts)

    def scan_audience_html(self, html: str) -> list[DistributorAlert]:
        """Detecta caida grande en monthly listeners."""
        if not html:
            return []
        listeners_text = self._extract_text(html, _SELECTOR_LISTENERS)
        listeners = self._parse_int_value(listeners_text) if listeners_text else None
        if listeners is None or listeners < 0:
            return []
        delta = self._baseline_cache.compute_delta_pct(
            DistributorPlatform.SPOTIFY_FOR_ARTISTS,
            "monthly_listeners",
            current_value=float(listeners),
        )
        self._baseline_cache.record_metric(
            DistributorPlatform.SPOTIFY_FOR_ARTISTS,
            "monthly_listeners",
            float(listeners),
        )
        if delta is not None and delta <= self._listeners_threshold:
            return [
                self._build_alert(
                    severity=AlertSeverity.CRITICAL,
                    category=AlertCategory.SUDDEN_STREAM_DROP,
                    message=(
                        f"S4A: monthly listeners cayeron {delta:.1f}% "
                        f"(umbral {self._listeners_threshold:.0f}%)"
                    ),
                    evidence=f"monthly_listeners={listeners}",
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
                    AND(date_gte=since.date(), from_="spotify.com")
                    if since
                    else AND(from_="spotify.com")
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
                                message="S4A email: cuenta cerrada",
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
                                message="S4A email: streams filtrados",
                                raw_evidence=haystack[:2_000],
                            )
                        )
        except Exception as exc:
            self._logger.warning("s4a_imap_fetch_failed", error=str(exc))
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
                    await session.goto(
                        _home_url(self._artist_id),
                        wait_until="domcontentloaded",
                    )
                except TargetSiteError:
                    return False
                url = await session.current_url()
                if "/login" in url.lower() or "accounts.spotify.com" in url.lower():
                    return False
                login_visible = await session.is_visible(_SELECTOR_LOGIN_FORM, timeout_ms=1500)
                return not login_visible
        except Exception as exc:
            self._logger.warning("s4a_is_authenticated_failed", error=str(exc))
            return False


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
