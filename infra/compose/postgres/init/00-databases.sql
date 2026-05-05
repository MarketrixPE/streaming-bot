-- Crea bases adicionales para Temporal (frontend + visibility).
-- Postgres ya creo POSTGRES_DB (streaming_bot) en bootstrap.
SELECT 'CREATE DATABASE temporal'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'temporal')\gexec

SELECT 'CREATE DATABASE temporal_visibility'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'temporal_visibility')\gexec
