"""Capa presentation/api: API REST FastAPI v1 read-only.

Esta capa expone los casos de uso del dominio (catalogo, jobs/sesiones,
accounts/personas y metricas) sobre HTTP/JSON. Todas las operaciones son
de lectura en v1; mutaciones se introducen en v2 con un nuevo router.

Composicion:
- ``app.create_app(settings, container)`` construye el FastAPI con el
  ciclo de vida correcto.
- ``server.main()`` levanta uvicorn como entry point.
- ``dependencies`` cablean container/session/usuario a los handlers.

La capa NUNCA importa modelos SQLAlchemy directamente: depende de los
puertos de dominio inyectados a traves del ``ApiDependencies`` wrapper
de ``streaming_bot.container``.
"""

from streaming_bot.presentation.api.app import create_app

__all__ = ["create_app"]
