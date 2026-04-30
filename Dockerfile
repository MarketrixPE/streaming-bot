# syntax=docker/dockerfile:1.7
# ----------------------------------------------------------------------------
# Multi-stage build con uv. Imagen final < 1.5 GB con Chromium incluido.
# ----------------------------------------------------------------------------

ARG PYTHON_VERSION=3.12

# ============================================================================
# Stage 1: builder - instala deps con uv (cacheado vía mounts)
# ============================================================================
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Cache de dependencias (lockfile primero para maximizar cache hits)
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev

# Copia el código y instala el paquete
COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

# ============================================================================
# Stage 2: runtime - Playwright base con Chromium ya instalado
# ============================================================================
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Usuario no-root (Playwright base trae 'pwuser')
COPY --from=builder --chown=pwuser:pwuser /app /app

USER pwuser

EXPOSE 9090
ENTRYPOINT ["streaming-bot"]
CMD ["--help"]
