"""Driver Postgres asyncpg + SQLAlchemy 2.0 async.

Los modelos se montan sobre `Base.metadata` para que Alembic pueda autogenerar
migraciones y los tests con SQLite in-memory puedan ejecutar `create_all`.

Patrón:
- `database.py` expone engine/sessionmaker/context manager transaccional.
- `models/` contiene la definición declarativa (estructura física).
- `repos/` contiene la implementación de los puertos de dominio (orquestación).
- `mappers.py` aísla la traducción modelo <-> entidad (sin I/O).
"""
