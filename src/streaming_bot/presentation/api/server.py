"""Entry point uvicorn de la API REST.

Uso:
    python -m streaming_bot.presentation.api.server
    SB_API__HOST=127.0.0.1 SB_API__PORT=9000 uvicorn streaming_bot.presentation.api.server:app

El binding host/port se controla via variables de entorno con prefijo
``SB_API__`` (delegado a ``ApiSettings``).
"""

from __future__ import annotations

import uvicorn

from streaming_bot.config import Settings
from streaming_bot.presentation.api.app import create_app

settings = Settings()
app = create_app(settings=settings)


def main() -> None:
    """Arranca uvicorn con la configuracion de ``ApiSettings``."""
    uvicorn.run(
        "streaming_bot.presentation.api.server:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=False,
        log_level=settings.observability.log_level.value,
        proxy_headers=True,
        access_log=False,
    )


if __name__ == "__main__":
    main()
