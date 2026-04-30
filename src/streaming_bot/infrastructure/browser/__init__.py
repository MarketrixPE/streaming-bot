"""Drivers de browser.

Mantenemos `PlaywrightDriver` por retrocompatibilidad (sólo IBrowserSession)
y exponemos `CamoufoxDriver` como driver moderno con primitivas humanas
(IRichBrowserSession) + Browserforge fingerprints.
"""

from streaming_bot.infrastructure.browser.browserforge_fingerprints import (
    BrowserforgeFingerprintGenerator,
)
from streaming_bot.infrastructure.browser.camoufox_driver import CamoufoxDriver
from streaming_bot.infrastructure.browser.camoufox_session import CamoufoxSession
from streaming_bot.infrastructure.browser.playwright_driver import PlaywrightDriver
from streaming_bot.infrastructure.browser.stealth_v2 import inject_stealth

__all__ = [
    "BrowserforgeFingerprintGenerator",
    "CamoufoxDriver",
    "CamoufoxSession",
    "PlaywrightDriver",
    "inject_stealth",
]
