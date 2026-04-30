"""Inyección de scripts anti-detección complementarios a los de Camoufox.

Camoufox (fork de Firefox) ya parchea internamente las superficies más obvias
(navigator.webdriver, plugins, WebGL). Estos scripts son refuerzos específicos
para casos donde Camoufox no llega o donde queremos consistencia con el
fingerprint coherente generado por Browserforge.

Niveles:
- "minimal":    sólo navigator.webdriver (refuerzo mínimo).
- "balanced":   añade Notification, plugins, WebGL alineado.
- "aggressive": añade canvas noise (ruido en getImageData). Riesgoso: puede
                romper sitios que dependen de canvas (lyrics renderers, etc.).
"""

from __future__ import annotations

from typing import Literal

from playwright.async_api import BrowserContext

from streaming_bot.domain.value_objects import Fingerprint

StealthLevel = Literal["minimal", "balanced", "aggressive"]


# Refuerzo: navigator.webdriver = undefined. Camoufox lo hace, pero sitios
# que parchean vuelven a "true" en algunos forks; doble seguro.
_NAVIGATOR_WEBDRIVER_PATCH = r"""
(() => {
  try {
    Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined });
  } catch (_) { /* ignore */ }
})();
"""

# Notification.permission = "default" (en headless suele venir como "denied").
_NOTIFICATION_PERMISSIONS_PATCH = r"""
(() => {
  try {
    if (typeof Notification !== 'undefined') {
      Object.defineProperty(Notification, 'permission', { get: () => 'default' });
    }
    const origQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (origQuery) {
      window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications'
          ? Promise.resolve({ state: 'default' })
          : origQuery.call(window.navigator.permissions, parameters)
      );
    }
  } catch (_) { /* ignore */ }
})();
"""

# navigator.plugins coherente: Chrome real expone PDF Viewer.
_PLUGINS_PATCH = r"""
(() => {
  try {
    const fakePlugins = [
      {
        name: 'PDF Viewer',
        filename: 'internal-pdf-viewer',
        description: 'Portable Document Format',
      },
      {
        name: 'Chrome PDF Viewer',
        filename: 'internal-pdf-viewer',
        description: '',
      },
    ];
    Object.defineProperty(navigator, 'plugins', { get: () => fakePlugins });
  } catch (_) { /* ignore */ }
})();
"""


# WebGL vendor/renderer alineado con UA: lo decidimos por familia de UA.
def _build_webgl_patch(fingerprint: Fingerprint) -> str:
    ua = fingerprint.user_agent.lower()
    if "windows" in ua:
        vendor = "Google Inc. (Intel)"
        renderer = "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)"
    elif "macintosh" in ua or "iphone" in ua:
        vendor, renderer = ("Apple Inc.", "Apple GPU")
    else:
        vendor, renderer = ("Intel Inc.", "Mesa Intel(R) Iris(R) Xe Graphics")
    return f"""
(() => {{
  try {{
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (parameter) {{
      if (parameter === 37445) return {vendor!r};
      if (parameter === 37446) return {renderer!r};
      return getParameter.apply(this, [parameter]);
    }};
  }} catch (_) {{ /* ignore */ }}
}})();
"""


# Canvas noise: añade jitter ±1 en algunos píxeles de toDataURL/getImageData.
# Trade-off: rompe Spotify Canvas (animaciones de fondo) y lyrics rendering;
# úsalo sólo en aggressive y cuando el sitio target lo tolere.
_CANVAS_NOISE_PATCH = r"""
(() => {
  try {
    const toDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function (...args) {
      const ctx = this.getContext('2d');
      if (ctx) {
        const w = this.width; const h = this.height;
        if (w > 0 && h > 0) {
          const img = ctx.getImageData(0, 0, w, h);
          for (let i = 0; i < img.data.length; i += 4) {
            if (Math.random() < 0.001) {
              img.data[i] = (img.data[i] + 1) & 0xFF;
            }
          }
          ctx.putImageData(img, 0, 0);
        }
      }
      return toDataURL.apply(this, args);
    };
  } catch (_) { /* ignore */ }
})();
"""


async def inject_stealth(
    context: BrowserContext,
    *,
    fingerprint: Fingerprint,
    level: StealthLevel = "balanced",
) -> None:
    """Inyecta scripts stealth en el contexto antes de cualquier petición.

    Idempotente por contexto (los scripts se añaden una sola vez por contexto).
    """
    scripts: list[str] = []

    # Niveles incrementales.
    scripts.append(_NAVIGATOR_WEBDRIVER_PATCH)

    if level in ("balanced", "aggressive"):
        scripts.append(_NOTIFICATION_PERMISSIONS_PATCH)
        scripts.append(_PLUGINS_PATCH)
        scripts.append(_build_webgl_patch(fingerprint))

    if level == "aggressive":
        scripts.append(_CANVAS_NOISE_PATCH)

    full_script = "\n".join(scripts)
    await context.add_init_script(full_script)
