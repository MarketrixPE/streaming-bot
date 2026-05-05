"""Adapters de infraestructura para el framework de A/B testing.

El paquete queda intencionalmente vacio: las implementaciones concretas
(repositorios Postgres, lector de eventos ClickHouse, escritor de overrides)
viven en sus subpaquetes correspondientes (``persistence/postgres/...``).
Mantener este modulo permite anadir adapters nuevos sin romper imports.
"""
