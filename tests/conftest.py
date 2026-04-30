"""Fixtures compartidos."""

from __future__ import annotations

import structlog


def pytest_configure() -> None:
    structlog.configure(
        processors=[structlog.processors.KeyValueRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(50),  # WARNING+
    )
