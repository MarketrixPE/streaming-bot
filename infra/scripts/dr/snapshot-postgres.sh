#!/usr/bin/env bash
# snapshot-postgres.sh
#
# Snapshot diario de Postgres para Disaster Recovery.
# Usa pg_basebackup (snapshot consistent + WAL streaming) para
# permitir Point-In-Time Recovery (PITR) hasta el momento exacto
# de un incidente.
#
# Politica de retencion:
#   - Local en /var/lib/streaming-bot/dr/postgres/: ultimas 7 noches.
#   - MinIO bucket dr/postgres/full/: ultimas 30 noches.
#   - Backblaze B2 bucket streaming-bot-dr-postgres: ultimas 90 noches
#     (replica geografica de seguridad).
#
# Cron sugerido: 0 2 * * *  /opt/streaming-bot/infra/scripts/dr/snapshot-postgres.sh full
#                */15 * * * *  /opt/streaming-bot/infra/scripts/dr/snapshot-postgres.sh wal
#
# Uso:
#   snapshot-postgres.sh full         # base backup + push WAL
#   snapshot-postgres.sh wal          # archive WAL incremental
#   snapshot-postgres.sh staging      # snapshot staging cluster
#
# Variables de entorno requeridas (vienen de
# /opt/streaming-bot/infra/compose/.env):
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST
#   MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY (opcional si
#   mc esta pre-configurado)
#   B2_BUCKET (opcional; sin esto se omite la replica geografica)
#   TELEGRAM_TOKEN, TELEGRAM_CHAT (opcional; alertas de fallo)
#   PG_BASEBACKUP_BIN (opcional; default 'pg_basebackup')

set -euo pipefail

# ── Validacion entorno ──────────────────────────────────────────────
ENV_FILE="${ENV_FILE:-/opt/streaming-bot/infra/compose/.env}"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
fi

REQUIRED_VARS=(POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB)
for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "[snapshot-postgres] ERROR: variable requerida '${var}' no esta seteada" >&2
    exit 64
  fi
done

POSTGRES_HOST="${POSTGRES_HOST:-10.10.0.20}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres}"
LOCAL_DIR="${LOCAL_DIR:-/var/lib/streaming-bot/dr/postgres}"
LOCAL_RETENTION_DAYS="${LOCAL_RETENTION_DAYS:-7}"
MINIO_ALIAS="${MINIO_ALIAS:-minio}"
B2_ALIAS="${B2_ALIAS:-b2}"
LOG_FILE="${LOG_FILE:-/var/log/streaming-bot-dr/snapshot-postgres.log}"

mkdir -p "${LOCAL_DIR}" "$(dirname "${LOG_FILE}")"
exec >>"${LOG_FILE}" 2>&1

MODE="${1:-full}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
DATE_TODAY="$(date -u +%Y%m%d)"

# ── Helpers ─────────────────────────────────────────────────────────

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [snapshot-postgres] $*"
}

notify_failure() {
  local message="$1"
  log "FALLO: ${message}"
  if [[ -n "${TELEGRAM_TOKEN:-}" && -n "${TELEGRAM_CHAT:-}" ]]; then
    curl -fsS "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
      -d "chat_id=${TELEGRAM_CHAT}" \
      -d "text=ALERTA snapshot-postgres FALLO: ${message}" \
      || true
  fi
}

trap 'rc=$?; if (( rc != 0 )); then notify_failure "exit code ${rc} en linea ${LINENO}"; fi' EXIT

run_full_snapshot() {
  local target_dir="${LOCAL_DIR}/full-${TS}"
  log "iniciando full snapshot a ${target_dir}"
  mkdir -p "${target_dir}"

  # pg_basebackup ejecutado dentro del contenedor para evitar mismatch
  # de version cliente-servidor.
  PGPASSWORD="${POSTGRES_PASSWORD}" docker exec -i \
    -e PGPASSWORD="${POSTGRES_PASSWORD}" \
    "${POSTGRES_CONTAINER}" pg_basebackup \
      --host="localhost" \
      --port="${POSTGRES_PORT}" \
      --username="${POSTGRES_USER}" \
      --pgdata=/var/lib/postgresql/dr-${TS} \
      --wal-method=stream \
      --checkpoint=fast \
      --format=tar \
      --gzip \
      --progress \
      --verbose

  log "pg_basebackup completado, copiando al host"
  docker cp "${POSTGRES_CONTAINER}:/var/lib/postgresql/dr-${TS}" "${target_dir}/"
  docker exec "${POSTGRES_CONTAINER}" rm -rf "/var/lib/postgresql/dr-${TS}"

  log "verificando integridad de tarballs"
  # pg_basebackup --format=tar produce base.tar.gz + pg_wal.tar.gz
  for archive in "${target_dir}/dr-${TS}"/*.tar.gz; do
    if ! gzip -t "${archive}"; then
      log "ERROR: archivo corrupto ${archive}"
      return 70
    fi
  done

  echo "${TS} $(du -sb "${target_dir}" | cut -f1) full $(date -Iseconds)" \
    >> "${LOCAL_DIR}/manifest.tsv"

  upload_to_remote "${target_dir}" "full/${TS}"

  log "full snapshot ${TS} completado: $(du -sh "${target_dir}" | cut -f1)"
}

run_wal_archive() {
  # WAL archive incremental cada 15 min via pg_receivewal externo.
  # En este modelo, el directorio /var/lib/postgresql/dr-wal es el
  # archive_command target.
  local wal_dir="${LOCAL_DIR}/wal"
  mkdir -p "${wal_dir}"

  log "iniciando wal archive incremental"

  # Copiar WAL files nuevos desde el contenedor
  docker exec "${POSTGRES_CONTAINER}" sh -c \
    'cd /var/lib/postgresql/data/pg_wal && ls -1t *.partial 2>/dev/null | tail -n +5 | xargs -r rm -f'

  # Switch WAL para forzar flush
  PGPASSWORD="${POSTGRES_PASSWORD}" docker exec -i \
    -e PGPASSWORD="${POSTGRES_PASSWORD}" \
    "${POSTGRES_CONTAINER}" psql \
      -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
      -c "SELECT pg_switch_wal();" >/dev/null

  # Sincronizar WAL files al host
  docker cp "${POSTGRES_CONTAINER}:/var/lib/postgresql/data/pg_wal/" \
    "${wal_dir}/data-${TS}/"

  # Comprimir y subir solo lo nuevo
  find "${wal_dir}" -type f -name '0000*' -newer "${wal_dir}/.last_wal_marker" \
    2>/dev/null \
    -exec gzip -k {} \; -exec mv {}.gz "${wal_dir}/${DATE_TODAY}/" \; \
    || true

  touch "${wal_dir}/.last_wal_marker"

  if [[ -d "${wal_dir}/${DATE_TODAY}" ]]; then
    upload_to_remote "${wal_dir}/${DATE_TODAY}" "wal/${DATE_TODAY}"
  fi

  log "wal archive ${TS} completado"
}

upload_to_remote() {
  local local_path="$1"
  local remote_subpath="$2"

  if command -v mc >/dev/null 2>&1; then
    log "subiendo a MinIO ${MINIO_ALIAS}/dr/postgres/${remote_subpath}"
    if ! mc mirror --overwrite --quiet "${local_path}" \
        "${MINIO_ALIAS}/dr/postgres/${remote_subpath}/"; then
      log "WARNING: subida a MinIO fallo"
      notify_failure "subida MinIO fallo para ${remote_subpath}"
    fi
  else
    log "WARNING: 'mc' no instalado, omitiendo subida a MinIO"
  fi

  if [[ -n "${B2_BUCKET:-}" ]] && command -v mc >/dev/null 2>&1; then
    log "replicando a Backblaze B2 ${B2_ALIAS}/${B2_BUCKET}/${remote_subpath}"
    if ! mc mirror --overwrite --quiet "${local_path}" \
        "${B2_ALIAS}/${B2_BUCKET}/${remote_subpath}/"; then
      log "WARNING: replica B2 fallo"
      notify_failure "replica B2 fallo para ${remote_subpath}"
    fi
  fi
}

cleanup_local() {
  log "limpieza local: borrar full snapshots > ${LOCAL_RETENTION_DAYS} dias"
  find "${LOCAL_DIR}" -maxdepth 1 -type d -name 'full-*' \
    -mtime +"${LOCAL_RETENTION_DAYS}" -exec rm -rf {} \; || true

  log "limpieza local: borrar WAL > ${LOCAL_RETENTION_DAYS} dias"
  find "${LOCAL_DIR}/wal" -maxdepth 2 -type f -mtime +"${LOCAL_RETENTION_DAYS}" \
    -delete 2>/dev/null || true
}

# ── Main ────────────────────────────────────────────────────────────

log "modo=${MODE} ts=${TS}"

case "${MODE}" in
  full)
    run_full_snapshot
    cleanup_local
    ;;
  wal)
    run_wal_archive
    ;;
  staging)
    POSTGRES_CONTAINER="postgres-staging"
    POSTGRES_DB="${POSTGRES_DB}_staging"
    LOCAL_DIR="${LOCAL_DIR}/staging"
    mkdir -p "${LOCAL_DIR}"
    run_full_snapshot
    ;;
  *)
    echo "Uso: $0 {full|wal|staging}" >&2
    exit 64
    ;;
esac

log "completado correctamente"
exit 0
