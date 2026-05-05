#!/usr/bin/env bash
# rotate-credentials.sh
#
# Rotacion de credenciales operativas (Postgres, Redis, Temporal,
# MinIO) + alerta Telegram al ops.
#
# Trigger:
#   - Cron trimestral: 0 4 1 */3 * /opt/streaming-bot/infra/scripts/dr/rotate-credentials.sh --quarterly
#   - Manual: durante incidente DR-6.
#
# Modos:
#   --quarterly  Rotacion programada trimestral (todos los services).
#   --emergency  Rotacion completa con kill_sessions previo (DR-6).
#   --service postgres|redis|temporal|minio  Rotacion individual.
#   --all        Equivalente a quarterly.
#
# Variables requeridas:
#   ENV_FILE (default /opt/streaming-bot/infra/compose/.env)
#   POSTGRES_USER, POSTGRES_PASSWORD (current)
#   REDIS_PASSWORD (current)
#   MINIO_ROOT_USER, MINIO_ROOT_PASSWORD (current)
#   TELEGRAM_TOKEN, TELEGRAM_CHAT
#
# CRITICA: este script regenera passwords/tokens y actualiza el
# .env. Hace commit de los cambios via sops (encrypted) si la flag
# --use-sops esta presente.

set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/streaming-bot/infra/compose/.env}"
ENV_BACKUP_DIR="${ENV_BACKUP_DIR:-/var/lib/streaming-bot/dr/secrets-backup}"
LOG_FILE="${LOG_FILE:-/var/log/streaming-bot-dr/rotate-credentials.log}"
USE_SOPS="${USE_SOPS:-false}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/streaming-bot/infra/compose}"

mkdir -p "${ENV_BACKUP_DIR}" "$(dirname "${LOG_FILE}")"
chmod 700 "${ENV_BACKUP_DIR}"

exec > >(tee -a "${LOG_FILE}") 2>&1

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[rotate-credentials] ERROR: ENV_FILE ${ENV_FILE} no existe" >&2
  exit 64
fi

# shellcheck disable=SC1090
source "${ENV_FILE}"

REQUIRED_VARS=(POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB REDIS_PASSWORD MINIO_ROOT_USER MINIO_ROOT_PASSWORD)
for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "[rotate-credentials] ERROR: variable '${var}' no esta seteada" >&2
    exit 64
  fi
done

# ── Parsing args ────────────────────────────────────────────────────

MODE=""
SERVICES=()

if [[ $# -lt 1 ]]; then
  echo "Uso: $0 {--quarterly|--emergency|--all|--service NAME} [--use-sops]" >&2
  exit 64
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quarterly|--all)
      MODE="quarterly"
      SERVICES=(postgres redis minio temporal sms_hub api_token)
      shift ;;
    --emergency)
      MODE="emergency"
      SERVICES=(postgres redis minio temporal sms_hub api_token)
      shift ;;
    --service)
      MODE="${MODE:-individual}"
      SERVICES+=("$2")
      shift 2 ;;
    --use-sops)
      USE_SOPS=true; shift ;;
    *)
      echo "[rotate-credentials] arg desconocido: $1" >&2
      exit 64 ;;
  esac
done

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [rotate-credentials] $*"
}

notify() {
  local message="$1"
  log "${message}"
  if [[ -n "${TELEGRAM_TOKEN:-}" && -n "${TELEGRAM_CHAT:-}" ]]; then
    curl -fsS "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
      -d "chat_id=${TELEGRAM_CHAT}" \
      -d "text=${message}" \
      || true
  fi
}

generate_secret() {
  # Password random 48 bytes base64 sin caracteres problematicos para .env
  openssl rand -base64 48 | tr -d '=+/\n' | head -c 48
}

backup_env_file() {
  local backup_file="${ENV_BACKUP_DIR}/env-pre-rotation-$(date -u +%Y%m%dT%H%M%SZ).tar.gz.gpg"
  log "backup encrypted del .env actual a ${backup_file}"
  tar -czf - -C "$(dirname "${ENV_FILE}")" "$(basename "${ENV_FILE}")" \
    | gpg --batch --symmetric --cipher-algo AES256 --output "${backup_file}" \
        --passphrase "${SECRET_BACKUP_PASSPHRASE:-CHANGE_ME_LONG_RANDOM}"
  chmod 400 "${backup_file}"
}

update_env_var() {
  local var_name="$1"
  local new_value="$2"
  if grep -qE "^${var_name}=" "${ENV_FILE}"; then
    sed -i.bak -E "s|^${var_name}=.*|${var_name}=${new_value}|" "${ENV_FILE}"
  else
    echo "${var_name}=${new_value}" >> "${ENV_FILE}"
  fi
  rm -f "${ENV_FILE}.bak"
}

restart_compose_service() {
  local service="$1"
  log "restart compose service ${service}"
  (cd "${COMPOSE_DIR}" && docker compose restart "${service}")
}

# ── Emergency: kill_sessions antes de rotar ────────────────────────

if [[ "${MODE}" == "emergency" ]]; then
  log "MODE=emergency: invalidando sesiones activas en Better Auth"
  PGPASSWORD="${POSTGRES_PASSWORD}" docker exec -i \
    -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres psql \
      -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
      -c "DELETE FROM auth_sessions; DELETE FROM auth_refresh_tokens;" \
    || log "WARNING: no se pudieron invalidar sesiones (puede no existir auth schema)"
fi

# ── Backup defensivo del .env ───────────────────────────────────────

backup_env_file

# ── Rotacion por servicio ──────────────────────────────────────────

rotate_postgres() {
  log "rotando POSTGRES_PASSWORD"
  local new_pw
  new_pw="$(generate_secret)"

  PGPASSWORD="${POSTGRES_PASSWORD}" docker exec -i \
    -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres psql \
      -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
      -c "ALTER USER ${POSTGRES_USER} WITH PASSWORD '${new_pw}';"

  update_env_var "POSTGRES_PASSWORD" "${new_pw}"

  # Actualizar SB_DATABASE__URL si esta en formato esperado
  if grep -q "^SB_DATABASE__URL=" "${ENV_FILE}"; then
    local current_url
    current_url="$(grep "^SB_DATABASE__URL=" "${ENV_FILE}" | cut -d= -f2-)"
    local new_url
    # Reemplaza la password en el connection string postgres:// o postgresql+asyncpg://
    new_url="$(echo "${current_url}" | sed -E "s|(://[^:]+:)[^@]+@|\\1${new_pw}@|")"
    update_env_var "SB_DATABASE__URL" "${new_url}"
  fi

  notify "POSTGRES_PASSWORD rotada $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  POSTGRES_PASSWORD="${new_pw}"
}

rotate_redis() {
  log "rotando REDIS_PASSWORD"
  local new_pw
  new_pw="$(generate_secret)"

  docker exec redis redis-cli -a "${REDIS_PASSWORD}" CONFIG SET requirepass "${new_pw}"
  update_env_var "REDIS_PASSWORD" "${new_pw}"

  notify "REDIS_PASSWORD rotada $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  REDIS_PASSWORD="${new_pw}"
}

rotate_minio() {
  log "rotando MINIO_ROOT_PASSWORD"
  local new_pw
  new_pw="$(generate_secret)"

  if command -v mc >/dev/null 2>&1; then
    mc admin user password minio "${MINIO_ROOT_USER}" "${new_pw}" \
      || log "WARNING: mc admin user password fallo, restart obligatorio"
  fi

  update_env_var "MINIO_ROOT_PASSWORD" "${new_pw}"
  restart_compose_service minio

  # Reconfigurar mc alias con la nueva password
  if command -v mc >/dev/null 2>&1; then
    mc alias set minio "http://10.10.0.20:9000" "${MINIO_ROOT_USER}" "${new_pw}"
  fi

  notify "MINIO_ROOT_PASSWORD rotada $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  MINIO_ROOT_PASSWORD="${new_pw}"
}

rotate_temporal() {
  log "rotando TEMPORAL_DB password (asociada a Postgres TEMPORAL_DB)"
  # Temporal usa una DB en el mismo cluster Postgres. Si TEMPORAL
  # tiene un user dedicado, rotarlo. Si no, depende del rotate_postgres.
  if PGPASSWORD="${POSTGRES_PASSWORD}" docker exec -i \
    -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
    psql -U "${POSTGRES_USER}" -d postgres \
    -tAc "SELECT 1 FROM pg_roles WHERE rolname='temporal'" | grep -q 1; then
      local new_pw
      new_pw="$(generate_secret)"
      PGPASSWORD="${POSTGRES_PASSWORD}" docker exec -i \
        -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres psql \
          -U "${POSTGRES_USER}" -d postgres \
          -c "ALTER USER temporal WITH PASSWORD '${new_pw}';"
      update_env_var "TEMPORAL_DB_PASSWORD" "${new_pw}"
      restart_compose_service temporal-server
      notify "TEMPORAL_DB_PASSWORD rotada $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  else
    log "Temporal usa user compartido con app, rotacion ya cubierta por rotate_postgres"
  fi
}

rotate_sms_hub() {
  log "rotando SMS_HUB_TOKEN"
  local new_token
  new_token="$(generate_secret)"
  update_env_var "SMS_HUB_TOKEN" "${new_token}"

  # Restart del container sms-hub en cada granja (asumiendo SSH key trust)
  for FARM in lt bg vn; do
    if ssh -o ConnectTimeout=5 "root@farm-${FARM}.${ENTITY_DOMAIN:-internal}" \
        "echo SMS_HUB_TOKEN=${new_token} > /opt/streaming-bot/infra/sms_hub/.env && \
         systemctl restart sms-hub" 2>/dev/null; then
      log "SMS hub farm-${FARM} restarted con nuevo token"
    else
      log "WARNING: no se pudo actualizar SMS hub en farm-${FARM} (puede no existir aun)"
    fi
  done

  notify "SMS_HUB_TOKEN rotado $(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

rotate_api_token() {
  log "rotando API_TOKEN (Better Auth API admin)"
  local new_token
  new_token="$(generate_secret)"
  update_env_var "API_TOKEN" "${new_token}"
  restart_compose_service api
  notify "API_TOKEN rotado $(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

# ── Ejecucion ───────────────────────────────────────────────────────

for service in "${SERVICES[@]}"; do
  case "${service}" in
    postgres) rotate_postgres ;;
    redis)    rotate_redis ;;
    minio)    rotate_minio ;;
    temporal) rotate_temporal ;;
    sms_hub)  rotate_sms_hub ;;
    api_token) rotate_api_token ;;
    *)
      log "WARNING: servicio '${service}' no reconocido, omitiendo"
      ;;
  esac
done

# ── Restart de la cadena que depende del .env ───────────────────────

log "restart compose stacks dependientes"
(cd "${COMPOSE_DIR}" && docker compose --env-file .env restart api worker dashboard) || true

# ── Sops commit (opcional) ──────────────────────────────────────────

if [[ "${USE_SOPS}" == true ]] && command -v sops >/dev/null 2>&1; then
  log "encriptando .env con sops y comiteando"
  cp "${ENV_FILE}" "${ENV_FILE}.encrypted.yaml"
  sops --encrypt --in-place "${ENV_FILE}.encrypted.yaml"
  if (cd "$(dirname "${ENV_FILE}")" && git rev-parse 2>/dev/null); then
    (cd "$(dirname "${ENV_FILE}")" && \
     git add "${ENV_FILE}.encrypted.yaml" && \
     git commit -m "[secrets] rotation $(date -u +%Y%m%dT%H%M%SZ)")
  fi
fi

# ── Reporte final ───────────────────────────────────────────────────

notify "rotate-credentials COMPLETADO services=${SERVICES[*]} mode=${MODE}"

cat <<EOM | tee -a "${LOG_FILE}"
================================================================
ROTATION SUMMARY
================================================================
Mode:     ${MODE}
Services: ${SERVICES[*]}
Backup:   ${ENV_BACKUP_DIR}/env-pre-rotation-* (encrypted)
Time:     $(date -u +%Y-%m-%dT%H:%M:%SZ)
================================================================
ACCIONES MANUALES REQUERIDAS:
  - Tokens de proveedores externos (CapSolver, 5SIM, ProxyEmpire,
    distros, banca APIs) deben rotarse manualmente desde sus UI.
  - SSH keys del laptop ops si fue compromiso (DR-6): editar
    /root/.ssh/authorized_keys en cada nodo.
  - WireGuard peer keys: usar infra/wireguard/rotate-peer.sh.
================================================================
EOM

exit 0
