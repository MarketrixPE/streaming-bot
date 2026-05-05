"""Puerto para resolutores de CAPTCHA (reCAPTCHA v2/v3, hCaptcha, Turnstile,
imagenes residuales tipo "select all squares with...").

Diseno DIP-friendly:
- El dominio solo conoce el contrato; cada adapter de infraestructura habla
  con su provider concreto (CapSolver, 2Captcha, GPT-4V, etc.).
- Todos los metodos son async porque los providers reales hacen I/O HTTP
  con polling de varios segundos.
- Los metodos devuelven el TOKEN o el TEXTO listo para inyectar en el
  formulario o el `g-recaptcha-response`. El caller decide donde lo pega.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from streaming_bot.domain.exceptions import DomainError


class CaptchaSolverError(DomainError):
    """Error tipado para fallas del puerto CAPTCHA (timeout, saldo, banneo)."""


@runtime_checkable
class ICaptchaSolver(Protocol):
    """Resuelve los formatos de CAPTCHA habituales en signup/login web.

    Convencion de retorno:
    - reCAPTCHA v2/v3 / hCaptcha / Turnstile: token (str) listo para
      asignar al input oculto correspondiente.
    - Imagen: texto resuelto (ej. "ABCD" o lista json-encoded de tiles
      seleccionados) tal y como lo emita el provider.
    """

    async def solve_recaptcha_v2(self, *, site_key: str, page_url: str) -> str:
        """Resuelve un reCAPTCHA v2 (checkbox/invisible). Retorna g-recaptcha-response."""
        ...

    async def solve_recaptcha_v3(
        self,
        *,
        site_key: str,
        page_url: str,
        action: str,
        min_score: float,
    ) -> str:
        """Resuelve un reCAPTCHA v3. `action` y `min_score` deben coincidir con
        los valores que la pagina espera para no ser descartado."""
        ...

    async def solve_hcaptcha(self, *, site_key: str, page_url: str) -> str:
        """Resuelve un hCaptcha. Retorna h-captcha-response."""
        ...

    async def solve_cloudflare_turnstile(self, *, site_key: str, page_url: str) -> str:
        """Resuelve un Cloudflare Turnstile. Retorna cf-turnstile-response."""
        ...

    async def solve_image_text(self, *, image_b64: str, hint: str) -> str:
        """Resuelve un CAPTCHA de imagen (texto distorsionado o seleccion de
        casillas). `hint` es una pista en lenguaje natural ("select all
        squares with traffic lights")."""
        ...
