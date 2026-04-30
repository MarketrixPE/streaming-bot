"""Patches anti-detección para el contexto Playwright.

Cubre los vectores comunes que delatan automatización:
- navigator.webdriver === true
- navigator.plugins vacío
- navigator.languages incoherente
- chrome.runtime ausente en Chrome
- WebGL vendor genérico
- permissions API que devuelve 'denied' siempre

Para producción seria, considerar `playwright-stealth` o `undetected-playwright`.
Aquí mantenemos un script auto-contenido para no depender de plugins externos.
"""

from __future__ import annotations

# Script inyectado vía add_init_script ANTES de cualquier petición de la página.
# Cada bloque parchea una superficie distinta. Mantener idempotente.
STEALTH_INIT_SCRIPT = r"""
(() => {
  // navigator.webdriver
  Object.defineProperty(navigator, 'webdriver', { get: () => false });

  // chrome runtime (presente en Chrome real)
  if (!window.chrome) {
    window.chrome = { runtime: {} };
  }

  // navigator.plugins (Chrome real tiene al menos PDF Viewer)
  Object.defineProperty(navigator, 'plugins', {
    get: () => [
      { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'PDF' },
      { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: '' },
    ],
  });

  // permissions API: notifications devuelve 'default' (no 'denied' como en headless)
  const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
  if (originalQuery) {
    window.navigator.permissions.query = (parameters) => (
      parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
    );
  }

  // WebGL vendor/renderer (headless Chrome devuelve 'Google Inc.' / 'SwiftShader')
  const getParameter = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function (parameter) {
    if (parameter === 37445) return 'Intel Inc.';            // UNMASKED_VENDOR_WEBGL
    if (parameter === 37446) return 'Intel Iris OpenGL Engine'; // UNMASKED_RENDERER_WEBGL
    return getParameter.apply(this, [parameter]);
  };

  // hardwareConcurrency / deviceMemory plausibles
  Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
  Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
})();
"""
