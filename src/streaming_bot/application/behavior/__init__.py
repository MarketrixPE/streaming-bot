"""Sub-paquete de behaviors humanos: ghost cursor + decision delays.

Modulos:
- `ghost_cursor`: trayectorias tipo `Xetera/ghost-cursor` (Bezier + overshoot
  + jitter + micro-pause) sobre `IRichBrowserSession`.
- `decision_delay`: politicas pluggables de delay de decision humana
  (log-normal por defecto, OpenAI opcional gateado por env).
"""

from streaming_bot.application.behavior.decision_delay import (
    DecisionDelayPolicy,
    DecisionType,
    LogNormalDelayPolicy,
    NullDelayPolicy,
    build_default_delay_policy,
)
from streaming_bot.application.behavior.ghost_cursor import (
    GhostCursorConfig,
    GhostCursorEngine,
)

__all__ = [
    "DecisionDelayPolicy",
    "DecisionType",
    "GhostCursorConfig",
    "GhostCursorEngine",
    "LogNormalDelayPolicy",
    "NullDelayPolicy",
    "build_default_delay_policy",
]
