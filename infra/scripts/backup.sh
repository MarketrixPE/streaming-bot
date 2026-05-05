#!/usr/bin/env bash
# Backup diario: dump Postgres + snapshot ClickHouse + sync MinIO a remoto.
# Ejecutar via cron: 0 3 * * * /opt/streaming-bot/infra/scripts/backup.sh
set -euo pipefail

LOG=/var/log/streaming-bot-backup.log
exec >>"$LOG" 2>&1
echo "[$(date -Iseconds)] backup begin"

source /opt/streaming-bot/infra/compose/.env

DATE=$(date +%Y%m%d-%H%M%S)
LOCAL_DIR=/var/lib/streaming-bot/backups/${DATE}
mkdir -p "$LOCAL_DIR"

# Postgres
docker exec postgres pg_dump \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  --format=custom --compress=9 \
  --file=/var/lib/postgresql/data/dump_${DATE}.dump
docker cp "postgres:/var/lib/postgresql/data/dump_${DATE}.dump" "$LOCAL_DIR/postgres.dump"
docker exec postgres rm "/var/lib/postgresql/data/dump_${DATE}.dump"

# ClickHouse
docker exec clickhouse clickhouse-backup create "ch_${DATE}"
docker exec clickhouse clickhouse-backup upload "ch_${DATE}" || echo "[warn] ch upload failed (pre-config?)"

# Sync a MinIO bucket "backups" (asumiendo mc configurado)
mc mirror --overwrite --remove "$LOCAL_DIR" "minio/backups/${DATE}/" || echo "[warn] mc sync skipped"

# Limpieza local: mantener 7 dias
find /var/lib/streaming-bot/backups -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +

echo "[$(date -Iseconds)] backup ok"
