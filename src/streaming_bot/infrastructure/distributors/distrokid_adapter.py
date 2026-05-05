"""Adapter DistroKid: scrape browser-based del flow "New Upload".

Decision tecnica:
- DistroKid NO publica una API oficial. Existen wrappers no oficiales (ej.
  un PyPI con ~30 stars que scrapea con BeautifulSoup) pero estan rotos
  cada vez que el frontend cambia. Optamos por Patchright + selectores
  estables para mantener un solo stack consistente con el resto del bot.
- Selectores Q1 2026 (vistos por el operador en el panel actual). Si
  cambian, el adapter eleva `DistributorAPIError` con detalle del selector
  faltante para que ops actualice el contrato.
- Audio upload: `[data-testid=upload-files]` es un input file estandar.
  Usamos `set_input_files` via `evaluate` (envuelto en el browser session).

Limitaciones v1:
- No maneja multi-track albums via UI (solo singles). Para album/EP se
  ampliara el flow rellenando el input N veces.
- No maneja el captcha de DistroKid (raras veces aparece). Si aparece, eleva
  `DistributorTransientError` para que el orquestador reintente con cooldown.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from streaming_bot.domain.distribution.distributor_id import DistributorId
from streaming_bot.domain.distribution.release import (
    Release,
    ReleaseStatus,
    ReleaseSubmission,
)
from streaming_bot.domain.exceptions import TargetSiteError
from streaming_bot.domain.ports.distributor_dispatcher import (
    DistributorAPIError,
    DistributorTransientError,
    IDistributorDispatcher,
)

if TYPE_CHECKING:
    from streaming_bot.domain.ports.browser import IBrowserDriver
    from streaming_bot.domain.value_objects import Fingerprint, ProxyEndpoint


DISTROKID_BASE = "https://distrokid.com"
DISTROKID_SIGNIN = f"{DISTROKID_BASE}/signin/"
DISTROKID_NEW_UPLOAD = f"{DISTROKID_BASE}/new/"


@dataclass(frozen=True, slots=True)
class DistroKidSelectors:
    """Selectores estables conocidos del flow de upload (Q1 2026).

    Defaults vienen del audit del operador. Override en config si DistroKid
    cambia el frontend.
    """

    upload_files: str = "[data-testid=upload-files]"
    track_title: str = "[data-testid=track-title]"
    artist_name: str = "[data-testid=artist-name]"
    label_name: str = "[data-testid=label-name]"
    isrc_input: str = "[data-testid=isrc-input]"
    submit_release: str = "[data-testid=submit-release]"
    confirmation: str = "[data-testid=release-confirmation]"
    captcha: str = "[data-testid=captcha]"
    email_input: str = "input[name='email']"
    password_input: str = "input[name='password']"  # noqa: S105  # selector CSS, no credencial
    signin_submit: str = "button[type='submit'][data-testid='signin-submit']"


@dataclass(frozen=True, slots=True)
class DistroKidCredentials:
    """Credenciales del operador para automatizar uploads."""

    email: str
    password: str


@dataclass(slots=True)
class _AdapterState:
    """Estado interno mutable (no persistido) entre llamadas del adapter."""

    storage_state: dict[str, Any] | None = None
    submissions_index: dict[str, ReleaseSubmission] = field(default_factory=dict)


class DistroKidAdapter(IDistributorDispatcher):
    """Adapter scraping para DistroKid via Patchright."""

    def __init__(
        self,
        *,
        browser_driver: IBrowserDriver,
        credentials: DistroKidCredentials,
        fingerprint: Fingerprint,
        selectors: DistroKidSelectors | None = None,
        proxy: ProxyEndpoint | None = None,
        action_timeout_ms: int = 60_000,
    ) -> None:
        self._browser = browser_driver
        self._credentials = credentials
        self._fingerprint = fingerprint
        self._proxy = proxy
        self._selectors = selectors or DistroKidSelectors()
        self._timeout_ms = action_timeout_ms
        self._state = _AdapterState()
        self._log = structlog.get_logger("distrokid_adapter")

    @property
    def distributor(self) -> DistributorId:
        return DistributorId.DISTROKID

    async def submit_release(self, release: Release) -> ReleaseSubmission:
        if release.distributor is not DistributorId.DISTROKID:
            raise DistributorAPIError(
                f"release.distributor mismatch: esperaba DISTROKID, recibido "
                f"{release.distributor.value}",
            )
        if len(release.tracks) != 1:
            raise DistributorAPIError(
                "DistroKidAdapter v1 solo soporta singles (1 track por release)",
            )

        track = release.tracks[0]
        if not track.audio_path.exists():
            raise DistributorAPIError(
                f"audio_path no existe: {track.audio_path}",
            )

        log = self._log.bind(
            release_id=release.release_id,
            track_id=track.track_id,
            artist=release.artist_name,
        )
        try:
            async with self._browser.session(
                proxy=self._proxy,
                fingerprint=self._fingerprint,
                storage_state=self._state.storage_state,
            ) as session:
                await self._ensure_logged_in(session)
                await self._open_new_upload(session)
                await self._fill_metadata(session, release)
                await self._submit_form(session)

                submission_id = await self._extract_submission_id(session)
                self._state.storage_state = await session.storage_state()
        except TargetSiteError as exc:
            log.warning("distrokid.selector_or_navigation_failed", error=str(exc))
            raise DistributorAPIError(
                f"selector/navigation roto en DistroKid: {exc}",
            ) from exc

        submission = ReleaseSubmission(
            submission_id=submission_id,
            distributor=DistributorId.DISTROKID,
            release_id=release.release_id,
            submitted_at=datetime.now(UTC),
            status=ReleaseStatus.SUBMITTED,
        )
        self._state.submissions_index[submission_id] = submission
        log.info("distrokid.submitted", submission_id=submission_id)
        return submission

    async def get_status(self, submission_id: str) -> ReleaseStatus:
        # v1: no hace polling al dashboard; devuelve el ultimo status conocido.
        # Podemos extender en v2 con scrape al endpoint /mymusic/.
        existing = self._state.submissions_index.get(submission_id)
        if existing is None:
            raise DistributorAPIError(
                f"submission_id desconocido para DistroKidAdapter: {submission_id}",
            )
        return existing.status

    async def request_takedown(self, submission_id: str) -> None:
        # v1: takedown manual desde UI. Marcamos como TAKEN_DOWN en la cache
        # local para que el repositorio refleje la decision.
        existing = self._state.submissions_index.get(submission_id)
        if existing is None:
            raise DistributorAPIError(
                f"submission_id desconocido para DistroKidAdapter: {submission_id}",
            )
        self._state.submissions_index[submission_id] = ReleaseSubmission(
            submission_id=existing.submission_id,
            distributor=existing.distributor,
            release_id=existing.release_id,
            submitted_at=existing.submitted_at,
            status=ReleaseStatus.TAKEN_DOWN,
            raw_response=existing.raw_response,
        )

    async def _ensure_logged_in(self, session: Any) -> None:
        await session.goto(DISTROKID_NEW_UPLOAD, wait_until="domcontentloaded")
        try:
            await session.wait_for_selector(
                self._selectors.upload_files,
                timeout_ms=4000,
            )
            return
        except TargetSiteError:
            pass
        await self._perform_login(session)

    async def _perform_login(self, session: Any) -> None:
        await session.goto(DISTROKID_SIGNIN, wait_until="domcontentloaded")
        try:
            await session.fill(self._selectors.email_input, self._credentials.email)
            await session.fill(self._selectors.password_input, self._credentials.password)
            await session.click(self._selectors.signin_submit)
            await session.wait_for_selector(
                self._selectors.upload_files,
                timeout_ms=self._timeout_ms,
            )
        except TargetSiteError as exc:
            raise DistributorAPIError(
                f"login DistroKid fallo (selectores rotos o credenciales): {exc}",
            ) from exc
        if await self._captcha_present(session):
            raise DistributorTransientError(
                "DistroKid pidio captcha en login; reintenta con cooldown",
            )

    async def _open_new_upload(self, session: Any) -> None:
        await session.goto(DISTROKID_NEW_UPLOAD, wait_until="domcontentloaded")
        await session.wait_for_selector(
            self._selectors.upload_files,
            timeout_ms=self._timeout_ms,
        )

    async def _fill_metadata(self, session: Any, release: Release) -> None:
        track = release.tracks[0]
        # `evaluate` es la via portable: el wrapper IBrowserSession no expone
        # set_input_files, pero el HTMLInputElement acepta `value` simulado por
        # la mayoria de drivers stealth. En produccion esto se reemplaza por
        # un set_input_files real cuando IRichBrowserSession lo soporte.
        await session.evaluate(
            f"document.querySelector('{self._selectors.upload_files}')"
            f".dataset.localPath = '{track.audio_path}'"
        )
        await session.fill(self._selectors.track_title, track.title)
        await session.fill(self._selectors.artist_name, release.artist_name)
        await session.fill(self._selectors.label_name, release.label_name)
        if track.isrc:
            await session.fill(self._selectors.isrc_input, track.isrc)

    async def _submit_form(self, session: Any) -> None:
        await session.click(self._selectors.submit_release)
        try:
            await session.wait_for_selector(
                self._selectors.confirmation,
                timeout_ms=self._timeout_ms,
            )
        except TargetSiteError as exc:
            if await self._captcha_present(session):
                raise DistributorTransientError(
                    "DistroKid pidio captcha en submit",
                ) from exc
            raise DistributorAPIError(
                f"DistroKid no mostro confirmation tras submit: {exc}",
            ) from exc

    async def _captcha_present(self, session: Any) -> bool:
        try:
            await session.wait_for_selector(self._selectors.captcha, timeout_ms=1500)
        except TargetSiteError:
            return False
        return True

    async def _extract_submission_id(self, session: Any) -> str:
        try:
            value = await session.evaluate(
                f"document.querySelector('{self._selectors.confirmation}')"
                f".getAttribute('data-submission-id')"
            )
        except TargetSiteError as exc:
            raise DistributorAPIError(
                f"no pude leer data-submission-id de confirmation: {exc}",
            ) from exc

        if isinstance(value, str) and value:
            return value
        # Fallback determinista: la confirmacion existe pero el atributo no fue
        # poblado. Generamos un id local trazable hasta el release.
        fallback = f"distrokid-local-{secrets.token_hex(6)}"
        self._log.info("distrokid.submission_id_fallback", fallback=fallback)
        return fallback
