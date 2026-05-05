"""Adapters de infraestructura para el dominio Deezer.

Solo `DeezerApiClient` por ahora: implementacion HTTPx de `IDeezerClient`
que habla con la API publica `api.deezer.com` para metadata y con la API
privada `gw-light.php` para acciones de usuario via cookies de sesion.
"""

from streaming_bot.infrastructure.deezer.deezer_api_client import DeezerApiClient

__all__ = ["DeezerApiClient"]
