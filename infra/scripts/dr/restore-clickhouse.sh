#!/usr/bin/env bash
# restore-clickhouse.sh
#
# Restore ClickHouse desde clickhouse-backup snapshot.
#
# Uso:
#   restore-clickhouse.sh latest                # ultimo full + incrementales
#   restore-clickhouse.sh full-20260103T030000Z # backup especifico
#   restore-clickhouse.sh latest --staging      # restaurar staging
#
# Variables requeridas: CLICKHOUSE_USER, CLICKHOUSE_PASSWORD,
# CLICKHOUSE_DB.

set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/streaming-bot/infra/compose/.env}"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
fi

REQUIRED_VARS=(CLICKHOUSE_USER CLICKHOUSE_PASSWORD CLICKHOUSE_DB)
for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "[restore-clickhouse] ERROR: variable '${var}' no esta seteada" >&2
    exit 64
  fi
done

CLICKHOUSE_CONTAINER="${CLICKHOUSE_CONTAINER:-clickhouse}"
LOG_FILE="${LOG_FILE:-/var/log/streaming-bot-dr/restore-clickhouse.log}"
MINIO_ALIAS="${MINIO_ALIAS:-minio}"
STAGING=false
FORCE_PROD=false

mkdir -p "$(dirname "${LOG_FILE}")"
exec > >(tee -a "${LOG_FILE}") 2>&1

if [[ $# -lt 1 ]]; then
  echo "Uso: $0 {latest|backup-name} [--staging] [--force]" >&2
  exit 64
fi

BACKUP_NAME="$1"; shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --staging) STAGING=true; shift ;;
    --force)   FORCE_PROD=true; shift ;;
    *) echo "[restore-clickhouse] arg desconocido: $1" >&2; exit 64 ;;
  esac
done

if [[ "${STAGING}" == true ]]; then
  CLICKHOUSE_CONTAINER="clickhouse-staging"
fi

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [restore-clickhouse] $*"
}

if [[ "${STAGING}" != true && "${FORCE_PROD}" != true ]]; then
  echo "WARNING: estas a punto de restaurar ClickHouse en PRODUCCION."
  echo "Esto descartara la base actual."
  echo "Para continuar pasa --force."
  exit 65
fi

ch_backup() {
  docker exec -i "${CLICKHOUSE_CONTAINER}" clickhouse-backup "$@"
}

# ── Resolver backup ─────────────────────────────────────────────────

if [[ "${BACKUP_NAME}" == "latest" ]]; then
  log "resolviendo latest backup remoto"
  BACKUP_NAME="$(ch_backup list remote | awk 'NR>1 {print $1}' | tail -1 || true)"
  if [[ -z "${BACKUP_NAME}" ]]; then
    log "ERROR: ningun backup remoto disponible"
    exit 70
  fi
  log "latest resuelto: ${BACKUP_NAME}"
fi

# ── Descargar backup desde remote ──────────────────────────────────

log "descargando ${BACKUP_NAME} desde remote_storage"
ch_backup download "${BACKUP_NAME}"

# ── Restore ─────────────────────────────────────────────────────────

log "ejecutando restore (drop existing + create + data)"
ch_backup restore "${BACKUP_NAME}" \
  --rm \
  --schema \
  --data \
  --resume

# ── Validacion ──────────────────────────────────────────────────────

log "validacion smoke: SELECT count desde tabla critica events"
docker exec "${CLICKHOUSE_CONTAINER}" clickhouse-client \
  --user "${CLICKHOUSE_USER}" \
  --password "${CLICKHOUSE_PASSWORD}" \
  --database "${CLICKHOUSE_DB}" \
  --query "SELECT COUNT(*) AS events_total FROM events"

docker exec "${CLICKHOUSE_CONTAINER}" clickhouse-client \
  --user "${CLICKHOUSE_USER}" \
  --password "${CLICKHOUSE_PASSWORD}" \
  --database "${CLICKHOUSE_DB}" \
  --query "SELECT MAX(event_time) AS most_recent_event FROM events"

log "RESTORE ClickHouse COMPLETADO desde ${BACKUP_NAME}"

if [[ -n "${TELEGRAM_TOKEN:-}" && -n "${TELEGRAM_CHAT:-}" ]]; then
  curl -fsS "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT}" \
    -d "text=RESTORE ClickHouse COMPLETADO desde backup ${BACKUP_NAME}" \
    || true
fi

exit 0
