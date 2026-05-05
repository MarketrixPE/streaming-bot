#!/usr/bin/env bash
# restore-postgres.sh
#
# Restore Postgres desde snapshot full + WAL replay para PITR.
#
# Modos:
#   restore-postgres.sh latest                       # restaura ultimo snapshot
#                                                    #  + replay WAL completo
#   restore-postgres.sh 20260103T020000Z             # restaura snapshot de
#                                                    #  esa fecha + replay
#   restore-postgres.sh 20260103T020000Z --pitr \
#       "2026-01-03 14:33:00+00"                     # PITR a momento exacto
#   restore-postgres.sh latest --staging             # restore en staging
#
# Variables de entorno requeridas:
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
#   ENV_FILE (opcional)
#
# CRITICA: este script DROP las tablas existentes y recarga el cluster.
# Confirma con --force si esta corriendo en produccion.

set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/streaming-bot/infra/compose/.env}"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
fi

REQUIRED_VARS=(POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB)
for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "[restore-postgres] ERROR: variable '${var}' no esta seteada" >&2
    exit 64
  fi
done

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres}"
LOCAL_DIR="${LOCAL_DIR:-/var/lib/streaming-bot/dr/postgres}"
MINIO_ALIAS="${MINIO_ALIAS:-minio}"
LOG_FILE="${LOG_FILE:-/var/log/streaming-bot-dr/restore-postgres.log}"

mkdir -p "$(dirname "${LOG_FILE}")"
exec > >(tee -a "${LOG_FILE}") 2>&1

# ── Parsing args ────────────────────────────────────────────────────

SNAPSHOT_ID=""
PITR_TARGET=""
STAGING=false
FORCE_PROD=false

if [[ $# -lt 1 ]]; then
  echo "Uso: $0 {latest|YYYYMMDDTHHMMSSZ} [--pitr 'YYYY-MM-DD HH:MM:SS+TZ'] [--staging] [--force]" >&2
  exit 64
fi

SNAPSHOT_ID="$1"; shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pitr)
      PITR_TARGET="$2"; shift 2 ;;
    --staging)
      STAGING=true; shift ;;
    --force)
      FORCE_PROD=true; shift ;;
    *)
      echo "[restore-postgres] argumento desconocido: $1" >&2
      exit 64
      ;;
  esac
done

if [[ "${STAGING}" == true ]]; then
  POSTGRES_CONTAINER="postgres-staging"
  POSTGRES_DB="${POSTGRES_DB}_staging"
  LOCAL_DIR="${LOCAL_DIR}/staging"
fi

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [restore-postgres] $*"
}

# ── Confirmacion produccion ─────────────────────────────────────────

if [[ "${STAGING}" != true && "${FORCE_PROD}" != true ]]; then
  echo "WARNING: estas a punto de restaurar el cluster Postgres de PRODUCCION."
  echo "Esto destruira el state actual del DB."
  echo "Para continuar pasa --force."
  exit 65
fi

# ── Resolver snapshot ────────────────────────────────────────────────

if [[ "${SNAPSHOT_ID}" == "latest" ]]; then
  if [[ -d "${LOCAL_DIR}" ]] && ls "${LOCAL_DIR}"/full-* >/dev/null 2>&1; then
    SNAPSHOT_DIR="$(ls -1d "${LOCAL_DIR}"/full-* | tail -1)"
    SNAPSHOT_ID="$(basename "${SNAPSHOT_DIR}" | sed 's/^full-//')"
    log "snapshot latest local resuelto: ${SNAPSHOT_ID}"
  else
    log "no hay snapshots locales, descargando ultimo de MinIO"
    if ! command -v mc >/dev/null 2>&1; then
      log "ERROR: 'mc' no instalado y no hay snapshots locales"
      exit 70
    fi
    SNAPSHOT_ID="$(mc ls "${MINIO_ALIAS}/dr/postgres/full/" \
                   | awk '{print $NF}' | tr -d '/' | sort | tail -1)"
    if [[ -z "${SNAPSHOT_ID}" ]]; then
      log "ERROR: ningun snapshot disponible en MinIO"
      exit 70
    fi
    SNAPSHOT_DIR="${LOCAL_DIR}/full-${SNAPSHOT_ID}"
    mkdir -p "${SNAPSHOT_DIR}"
    mc mirror "${MINIO_ALIAS}/dr/postgres/full/${SNAPSHOT_ID}/" "${SNAPSHOT_DIR}/"
  fi
else
  SNAPSHOT_DIR="${LOCAL_DIR}/full-${SNAPSHOT_ID}"
  if [[ ! -d "${SNAPSHOT_DIR}" ]]; then
    log "snapshot ${SNAPSHOT_ID} no esta local, descargando de MinIO"
    if ! command -v mc >/dev/null 2>&1; then
      log "ERROR: 'mc' no instalado"
      exit 70
    fi
    mkdir -p "${SNAPSHOT_DIR}"
    mc mirror "${MINIO_ALIAS}/dr/postgres/full/${SNAPSHOT_ID}/" "${SNAPSHOT_DIR}/"
  fi
fi

log "usando snapshot dir: ${SNAPSHOT_DIR}"

# ── Verificacion integridad ─────────────────────────────────────────

log "verificando integridad de tarballs"
for archive in "${SNAPSHOT_DIR}"/dr-*/*.tar.gz; do
  if ! gzip -t "${archive}"; then
    log "ERROR: tarball corrupto ${archive}"
    exit 70
  fi
done

# ── Stop Postgres antes del restore ─────────────────────────────────

log "deteniendo contenedor ${POSTGRES_CONTAINER}"
docker stop "${POSTGRES_CONTAINER}" || log "WARNING: contenedor ya detenido"

# ── Backup defensivo del data dir actual ───────────────────────────

DATA_VOL="$(docker inspect "${POSTGRES_CONTAINER}" --format '{{ range .Mounts }}{{ if eq .Destination "/var/lib/postgresql/data" }}{{ .Source }}{{ end }}{{ end }}' || true)"
if [[ -n "${DATA_VOL}" && -d "${DATA_VOL}" ]]; then
  BACKUP_VOL="${DATA_VOL}.pre-restore-$(date -u +%Y%m%dT%H%M%SZ)"
  log "moviendo data dir actual a ${BACKUP_VOL} (defensa)"
  mv "${DATA_VOL}" "${BACKUP_VOL}"
  mkdir -p "${DATA_VOL}"
  chown 999:999 "${DATA_VOL}" || true
fi

# ── Extraer snapshot al data dir ────────────────────────────────────

log "extrayendo base.tar.gz"
tar -xzf "${SNAPSHOT_DIR}/dr-${SNAPSHOT_ID}/base.tar.gz" -C "${DATA_VOL}"
log "extrayendo pg_wal.tar.gz"
tar -xzf "${SNAPSHOT_DIR}/dr-${SNAPSHOT_ID}/pg_wal.tar.gz" -C "${DATA_VOL}/pg_wal/"

# ── Configurar recovery (PITR si aplica) ───────────────────────────

if [[ -n "${PITR_TARGET}" ]]; then
  log "configurando PITR target: ${PITR_TARGET}"

  # Descargar WAL files necesarios desde MinIO
  WAL_DIR="${LOCAL_DIR}/wal"
  mkdir -p "${WAL_DIR}"
  if command -v mc >/dev/null 2>&1; then
    PITR_DATE_DAY="$(echo "${PITR_TARGET}" | awk '{print $1}' | tr -d '-')"
    SNAPSHOT_DAY="$(echo "${SNAPSHOT_ID}" | cut -c1-8)"
    for day in "${SNAPSHOT_DAY}" "${PITR_DATE_DAY}"; do
      mc mirror "${MINIO_ALIAS}/dr/postgres/wal/${day}/" "${WAL_DIR}/${day}/" || true
    done
  fi

  cat > "${DATA_VOL}/postgresql.auto.conf.dr" <<EOF
restore_command = 'gunzip -c ${WAL_DIR}/$(date -u +%Y%m%d)/%f.gz > %p || cp /var/lib/postgresql/wal-archive/%f %p'
recovery_target_time = '${PITR_TARGET}'
recovery_target_action = 'promote'
EOF

  cat "${DATA_VOL}/postgresql.auto.conf.dr" >> "${DATA_VOL}/postgresql.auto.conf"
  touch "${DATA_VOL}/recovery.signal"

  # Mount del WAL archive en el contenedor (asume bind mount existente)
  log "PITR config aplicada, recovery.signal touched"
else
  log "no PITR target, replay completo de WAL hasta el final del snapshot"
  touch "${DATA_VOL}/recovery.signal"
fi

# ── Arrancar Postgres y esperar recovery ───────────────────────────

log "arrancando ${POSTGRES_CONTAINER}"
docker start "${POSTGRES_CONTAINER}"

log "esperando recovery (timeout 600s)"
for _ in $(seq 1 60); do
  if docker exec "${POSTGRES_CONTAINER}" pg_isready -U "${POSTGRES_USER}" >/dev/null 2>&1; then
    log "Postgres listo"
    break
  fi
  sleep 10
done

if ! docker exec "${POSTGRES_CONTAINER}" pg_isready -U "${POSTGRES_USER}" >/dev/null 2>&1; then
  log "ERROR: Postgres no levanto en 600s"
  exit 75
fi

# ── Validacion post-restore ────────────────────────────────────────

log "validacion smoke: SELECT recent COUNT desde tabla critica accounts"
PGPASSWORD="${POSTGRES_PASSWORD}" docker exec -i \
  -e PGPASSWORD="${POSTGRES_PASSWORD}" \
  "${POSTGRES_CONTAINER}" psql \
    -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    -c "SELECT COUNT(*) AS accounts_total FROM accounts;" \
    -c "SELECT MAX(updated_at) AS most_recent_update FROM accounts;"

log "RESTORE COMPLETADO. backup defensivo en: ${BACKUP_VOL:-N/A}"

if [[ -n "${TELEGRAM_TOKEN:-}" && -n "${TELEGRAM_CHAT:-}" ]]; then
  curl -fsS "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT}" \
    -d "text=RESTORE Postgres COMPLETADO desde snapshot ${SNAPSHOT_ID}${PITR_TARGET:+ PITR=$PITR_TARGET}" \
    || true
fi

exit 0
