"""Helper interactivo para obtener refresh_token de usuario (OAuth PKCE flow).

NOTA: Este módulo es SOLO para uso interactivo/setup. No se usa en runtime.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import secrets
import socketserver
import urllib.parse
import webbrowser
from typing import TYPE_CHECKING

import httpx

from streaming_bot.infrastructure.spotify.errors import SpotifyAuthError

if TYPE_CHECKING:
    from streaming_bot.infrastructure.spotify.config import SpotifyConfig


def _generate_pkce_pair() -> tuple[str, str]:
    """Genera code_verifier y code_challenge (S256) para PKCE."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("utf-8")).digest())
        .decode("utf-8")
        .rstrip("=")
    )
    return code_verifier, code_challenge


async def obtain_user_refresh_token(config: SpotifyConfig, scopes: list[str]) -> str:
    """Obtiene un refresh_token de usuario mediante OAuth PKCE flow.

    INTERACTIVE ONLY: Este método abre un navegador y levanta un servidor HTTP local
    para capturar el callback de Spotify. Debe usarse solo durante setup/configuración.

    Args:
        config: Configuración con client_id, client_secret, redirect_uri.
        scopes: Lista de scopes OAuth (e.g. ["playlist-modify-public", "playlist-modify-private"]).

    Returns:
        El refresh_token que puede guardarse en config.user_refresh_token.

    Raises:
        SpotifyAuthError: Si el flujo OAuth falla.
    """
    code_verifier, code_challenge = _generate_pkce_pair()
    state = secrets.token_urlsafe(16)

    authorize_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(
        {
            "client_id": config.client_id,
            "response_type": "code",
            "redirect_uri": config.redirect_uri,
            "state": state,
            "scope": " ".join(scopes),
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
        }
    )

    print(f"Abriendo navegador en:\n{authorize_url}\n")
    webbrowser.open(authorize_url)

    auth_code: str | None = None
    received_state: str | None = None

    class CallbackHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self) -> None:
            nonlocal auth_code, received_state
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)

            if "code" in params and "state" in params:
                auth_code = params["code"][0]
                received_state = params["state"][0]
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>OK! Ya puedes cerrar esta ventana.</h1>")
            else:
                self.send_response(400)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>Error: missing code or state</h1>")

        def log_message(self, format: str, *args: object) -> None:
            pass

    port = int(config.redirect_uri.split(":")[-1].split("/")[0])
    with socketserver.TCPServer(("127.0.0.1", port), CallbackHandler) as httpd:
        print(f"Esperando callback en {config.redirect_uri}...")
        httpd.handle_request()

    if not auth_code or received_state != state:
        raise SpotifyAuthError("OAuth callback failed: invalid state or missing code")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "authorization_code",
                    "code": auth_code,
                    "redirect_uri": config.redirect_uri,
                    "client_id": config.client_id,
                    "code_verifier": code_verifier,
                },
                timeout=config.request_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise SpotifyAuthError(f"Token exchange failed: {e.response.status_code}") from e

    data = response.json()
    refresh_token: str = data["refresh_token"]
    return refresh_token
