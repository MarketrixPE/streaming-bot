"""Drivers de browser.

Catalogo:
- `PlaywrightDriver`: legacy (solo IBrowserSession), Chromium estandar.
- `PatchrightDriver`: Chromium patched (mejor stealth que Playwright vanilla).
- `CamoufoxDriver`: Firefox stealth + Browserforge fingerprints (IRichBrowserSession).
- `MixedBrowserDriver`: agregador 70/30 Patchright + Camoufox (recomendado prod).
"""

from streaming_bot.infrastructure.browser.browserforge_fingerprints import (
    BrowserforgeFingerprintGenerator,
)
from streaming_bot.infrastructure.browser.camoufox_driver import CamoufoxDriver
from streaming_bot.infrastructure.browser.camoufox_session import CamoufoxSession
from streaming_bot.infrastructure.browser.mixed_browser_driver import MixedBrowserDriver
from streaming_bot.infrastructure.browser.patchright_driver import PatchrightDriver
from streaming_bot.infrastructure.browser.playwright_driver import PlaywrightDriver
from streaming_bot.infrastructure.browser.stealth_v2 import inject_stealth

__all__ = [
    "BrowserforgeFingerprintGenerator",
    "CamoufoxDriver",
    "CamoufoxSession",
    "MixedBrowserDriver",
    "PatchrightDriver",
    "PlaywrightDriver",
    "inject_stealth",
]
