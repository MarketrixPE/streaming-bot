#!/usr/bin/env bash
# Restore desde backup remoto en MinIO.
# Uso: ./restore.sh 20260103-030000
set -euo pipefail

DATE="${1:?Uso: $0 YYYYMMDD-HHMMSS}"
WORK=/tmp/restore-${DATE}
mkdir -p "$WORK"

source /opt/streaming-bot/infra/compose/.env

echo "[1/3] Descargando backup ${DATE} desde MinIO..."
mc mirror --overwrite "minio/backups/${DATE}/" "$WORK/"

echo "[2/3] Restaurando Postgres..."
docker cp "$WORK/postgres.dump" postgres:/tmp/postgres.dump
docker exec postgres pg_restore \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  --clean --if-exists \
  /tmp/postgres.dump
docker exec postgres rm /tmp/postgres.dump

echo "[3/3] Restaurando ClickHouse (manual: docker exec clickhouse clickhouse-backup restore ch_${DATE})"

echo "Restore ${DATE} completo."
