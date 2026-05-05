"""Adapter RouteNote: HTTP REST con cookies de session persistidas.

RouteNote tiene una API privada accesible al usuario logado. El flujo de
autenticacion oficial publico no expone API keys: usamos las cookies de
session emitidas por `/api/auth/login` (o por login UI fuera de banda) y
las refrescamos cuando 401.

Endpoints conocidos Q1 2026 (visto en network tab del UI):
- POST `/api/auth/login`               -> set-cookie de session
- POST `/api/release/create`           -> crea release (multipart audio)
- GET  `/api/release/{id}`             -> consulta estado
- POST `/api/release/{id}/takedown`    -> request takedown
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from streaming_bot.domain.distribution.distributor_id import DistributorId
from streaming_bot.domain.distribution.release import (
    Release,
    ReleaseStatus,
    ReleaseSubmission,
)
from streaming_bot.domain.ports.distributor_dispatcher import (
    DistributorAPIError,
    DistributorTransientError,
    IDistributorDispatcher,
)

ROUTENOTE_BASE = "https://routenote.com"
ROUTENOTE_LOGIN = f"{ROUTENOTE_BASE}/api/auth/login"
ROUTENOTE_CREATE = f"{ROUTENOTE_BASE}/api/release/create"


@dataclass(frozen=True, slots=True)
class RouteNoteCredentials:
    email: str
    password: str


_STATUS_MAP: dict[str, ReleaseStatus] = {
    "draft": ReleaseStatus.DRAFT,
    "submitted": ReleaseStatus.SUBMITTED,
    "in_review": ReleaseStatus.IN_REVIEW,
    "live": ReleaseStatus.LIVE,
    "rejected": ReleaseStatus.REJECTED,
    "taken_down": ReleaseStatus.TAKEN_DOWN,
}


class RouteNoteAdapter(IDistributorDispatcher):
    """Adapter HTTP para RouteNote.

    Usa `httpx.AsyncClient` reutilizable (cookie jar persistente) y reintenta
    el login solo cuando el servidor devuelve 401.
    """

    def __init__(
        self,
        *,
        credentials: RouteNoteCredentials,
        client: httpx.AsyncClient | None = None,
        base_url: str = ROUTENOTE_BASE,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self._credentials = credentials
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=request_timeout_seconds,
            follow_redirects=True,
        )
        self._authenticated = False
        self._log = structlog.get_logger("routenote_adapter")

    @property
    def distributor(self) -> DistributorId:
        return DistributorId.ROUTENOTE

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def submit_release(self, release: Release) -> ReleaseSubmission:
        if release.distributor is not DistributorId.ROUTENOTE:
            raise DistributorAPIError(
                f"release.distributor mismatch: esperaba ROUTENOTE, recibido "
                f"{release.distributor.value}",
            )
        await self._ensure_authenticated()

        payload = self._build_payload(release)
        response = await self._post_json("/api/release/create", payload)
        if response.status_code == 401:
            self._authenticated = False
            await self._ensure_authenticated()
            response = await self._post_json("/api/release/create", payload)

        self._raise_for_status(response, action="create_release")

        body = self._parse_json(response, action="create_release")
        submission_id = body.get("release_id") or body.get("id")
        if not isinstance(submission_id, str) or not submission_id:
            raise DistributorAPIError(
                f"RouteNote create_release sin release_id: body={body!r}",
            )
        status = _STATUS_MAP.get(str(body.get("status", "submitted")), ReleaseStatus.SUBMITTED)
        return ReleaseSubmission(
            submission_id=submission_id,
            distributor=DistributorId.ROUTENOTE,
            release_id=release.release_id,
            submitted_at=datetime.now(UTC),
            status=status,
            raw_response=response.text[:1024],
        )

    async def get_status(self, submission_id: str) -> ReleaseStatus:
        await self._ensure_authenticated()
        response = await self._get(f"/api/release/{submission_id}")
        self._raise_for_status(response, action="get_status")
        body = self._parse_json(response, action="get_status")
        return _STATUS_MAP.get(str(body.get("status", "")), ReleaseStatus.SUBMITTED)

    async def request_takedown(self, submission_id: str) -> None:
        await self._ensure_authenticated()
        response = await self._post_json(
            f"/api/release/{submission_id}/takedown",
            payload={"reason": "operator_initiated"},
        )
        self._raise_for_status(response, action="request_takedown")

    async def _ensure_authenticated(self) -> None:
        if self._authenticated:
            return
        response = await self._post_json(
            "/api/auth/login",
            payload={
                "email": self._credentials.email,
                "password": self._credentials.password,
            },
        )
        if response.status_code == 401:
            raise DistributorAPIError("RouteNote credenciales invalidas")
        self._raise_for_status(response, action="login")
        self._authenticated = True
        self._log.info("routenote.login_ok")

    async def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        try:
            return await self._client.post(path, json=payload)
        except httpx.RequestError as exc:
            raise DistributorTransientError(
                f"RouteNote network error en {path}: {exc}",
            ) from exc

    async def _get(self, path: str) -> httpx.Response:
        try:
            return await self._client.get(path)
        except httpx.RequestError as exc:
            raise DistributorTransientError(
                f"RouteNote network error en {path}: {exc}",
            ) from exc

    def _build_payload(self, release: Release) -> dict[str, Any]:
        track_payloads = [
            {
                "title": track.title,
                "artist_name": track.artist_name,
                "isrc": track.isrc,
                "duration_seconds": track.duration_seconds,
                "explicit": track.explicit,
                "audio_path": str(track.audio_path),
            }
            for track in release.tracks
        ]
        return {
            "release_id": release.release_id,
            "artist_name": release.artist_name,
            "label_name": release.label_name,
            "release_date": release.release_date.isoformat(),
            "isrc": release.isrc,
            "upc": release.upc,
            "tracks": track_payloads,
        }

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, action: str) -> None:
        if response.is_success:
            return
        # 4xx -> permanente, 5xx -> transient.
        snippet = response.text[:300]
        if 500 <= response.status_code < 600:
            raise DistributorTransientError(
                f"RouteNote 5xx en {action}: status={response.status_code} body={snippet!r}",
            )
        raise DistributorAPIError(
            f"RouteNote {response.status_code} en {action}: body={snippet!r}",
        )

    @staticmethod
    def _parse_json(response: httpx.Response, *, action: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise DistributorAPIError(
                f"RouteNote {action} respuesta no JSON: {response.text[:200]!r}",
            ) from exc
        if not isinstance(payload, dict):
            raise DistributorAPIError(
                f"RouteNote {action} JSON no es dict: {payload!r}",
            )
        return payload
