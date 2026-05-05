"""Stack CAPTCHA solver: adapters HTTP + router con failover y budget guard."""

from streaming_bot.infrastructure.captcha.budget_guard import BudgetGuard
from streaming_bot.infrastructure.captcha.capsolver_adapter import (
    DEFAULT_BASE_URL as CAPSOLVER_BASE_URL,
)
from streaming_bot.infrastructure.captcha.capsolver_adapter import CapSolverAdapter
from streaming_bot.infrastructure.captcha.captcha_router import (
    DEFAULT_PROVIDER_COSTS,
    CaptchaCostTable,
    CaptchaSolverRouter,
)
from streaming_bot.infrastructure.captcha.gpt4v_image_solver import (
    Gpt4vBackend,
    Gpt4vImageSolver,
)
from streaming_bot.infrastructure.captcha.twocaptcha_adapter import (
    DEFAULT_BASE_URL as TWOCAPTCHA_BASE_URL,
)
from streaming_bot.infrastructure.captcha.twocaptcha_adapter import TwoCaptchaAdapter

__all__ = [
    "CAPSOLVER_BASE_URL",
    "DEFAULT_PROVIDER_COSTS",
    "TWOCAPTCHA_BASE_URL",
    "BudgetGuard",
    "CapSolverAdapter",
    "CaptchaCostTable",
    "CaptchaSolverRouter",
    "Gpt4vBackend",
    "Gpt4vImageSolver",
    "TwoCaptchaAdapter",
]
