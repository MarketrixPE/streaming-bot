#!/usr/bin/env bash
# snapshot-clickhouse.sh
#
# Snapshot diario de ClickHouse usando clickhouse-backup.
# Politica:
#   - Domingo: backup full.
#   - L-S: backup incremental basado en ultimo full.
#   - Push a MinIO + replica B2.
#
# Cron sugerido:
#   0 3 * * 0   /opt/streaming-bot/infra/scripts/dr/snapshot-clickhouse.sh full
#   0 3 * * 1-6 /opt/streaming-bot/infra/scripts/dr/snapshot-clickhouse.sh incremental
#
# Variables requeridas:
#   CLICKHOUSE_USER, CLICKHOUSE_PASSWORD, CLICKHOUSE_DB
#   ENV_FILE (opcional)

set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/streaming-bot/infra/compose/.env}"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
fi

REQUIRED_VARS=(CLICKHOUSE_USER CLICKHOUSE_PASSWORD CLICKHOUSE_DB)
for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "[snapshot-clickhouse] ERROR: variable '${var}' no esta seteada" >&2
    exit 64
  fi
done

CLICKHOUSE_CONTAINER="${CLICKHOUSE_CONTAINER:-clickhouse}"
LOCAL_DIR="${LOCAL_DIR:-/var/lib/streaming-bot/dr/clickhouse}"
LOCAL_RETENTION_DAYS="${LOCAL_RETENTION_DAYS:-14}"
MINIO_ALIAS="${MINIO_ALIAS:-minio}"
B2_ALIAS="${B2_ALIAS:-b2}"
LOG_FILE="${LOG_FILE:-/var/log/streaming-bot-dr/snapshot-clickhouse.log}"

mkdir -p "${LOCAL_DIR}" "$(dirname "${LOG_FILE}")"
exec >>"${LOG_FILE}" 2>&1

MODE="${1:-full}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [snapshot-clickhouse] $*"
}

notify_failure() {
  local message="$1"
  log "FALLO: ${message}"
  if [[ -n "${TELEGRAM_TOKEN:-}" && -n "${TELEGRAM_CHAT:-}" ]]; then
    curl -fsS "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
      -d "chat_id=${TELEGRAM_CHAT}" \
      -d "text=ALERTA snapshot-clickhouse FALLO: ${message}" \
      || true
  fi
}

trap 'rc=$?; if (( rc != 0 )); then notify_failure "exit code ${rc} en linea ${LINENO}"; fi' EXIT

# clickhouse-backup binary se asume instalado dentro del contenedor.
ch_backup() {
  docker exec -i "${CLICKHOUSE_CONTAINER}" clickhouse-backup "$@"
}

run_full() {
  local backup_name="full-${TS}"
  log "creando full backup ${backup_name}"
  ch_backup create "${backup_name}"

  log "subiendo backup ${backup_name} a MinIO + B2 via remote_storage"
  ch_backup upload "${backup_name}"

  log "manteniendo full localmente y purgando viejos > ${LOCAL_RETENTION_DAYS} dias"
  ch_backup list local | awk '/full-/ {print $1}' | while read -r b; do
    ts_part="$(echo "${b}" | sed 's/^full-//' | head -c8)"
    age_days="$(( ($(date -u +%s) - $(date -u -d "${ts_part}" +%s 2>/dev/null || date -u +%s)) / 86400 ))"
    if [[ "${age_days}" -gt "${LOCAL_RETENTION_DAYS}" ]]; then
      log "purgando local ${b} (${age_days} dias)"
      ch_backup delete local "${b}" || true
    fi
  done
}

run_incremental() {
  local last_full
  last_full="$(ch_backup list local | awk '/full-/ {print $1}' | tail -1 || true)"
  if [[ -z "${last_full}" ]]; then
    log "WARNING: no hay full backup local, ejecutando full en su lugar"
    run_full
    return
  fi

  local backup_name="inc-${TS}"
  log "creando incremental ${backup_name} basado en ${last_full}"
  ch_backup create_remote --diff-from-remote="${last_full}" "${backup_name}"

  log "incremental ${backup_name} subido al remote storage"
}

# ── Main ────────────────────────────────────────────────────────────

log "modo=${MODE}"

case "${MODE}" in
  full) run_full ;;
  incremental|inc) run_incremental ;;
  *)
    echo "Uso: $0 {full|incremental}" >&2
    exit 64
    ;;
esac

# Validacion: el backup esta efectivamente en MinIO
if command -v mc >/dev/null 2>&1; then
  if mc ls "${MINIO_ALIAS}/dr/clickhouse/" | grep -q "$(date -u +%Y%m%d)"; then
    log "validacion ok: backup del dia presente en MinIO"
  else
    notify_failure "backup del dia NO encontrado en MinIO"
  fi
fi

log "completado correctamente"
exit 0
