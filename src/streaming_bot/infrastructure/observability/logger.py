"""Logger estructurado con structlog. JSON en prod, consola con colores en dev."""

from __future__ import annotations

import logging
import sys

import structlog
from structlog.stdlib import BoundLogger

from streaming_bot.config import LogFormat, LogLevel


def configure_logging(*, level: LogLevel, fmt: LogFormat) -> None:
    """Configura structlog + stdlib logging globalmente."""

    log_level = getattr(logging, level.value.upper())

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        timestamper,
    ]

    if fmt == LogFormat.JSON:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "streaming_bot") -> BoundLogger:
    """Devuelve un logger estructurado."""
    logger: BoundLogger = structlog.get_logger(name)
    return logger
