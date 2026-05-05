#!/usr/bin/env bash
# provision-modem.sh
#
# Registra un modem nuevo en la tabla `farm_modems` (consumida por
# el SMS hub) Y en la tabla `modems` del control plane (consumida
# por el motor de routing).
#
# Asume que el modem fisico ya esta:
#   - Conectado al USB hub del farm host.
#   - Detectado en /dev/ttyUSBN o /dev/serial/by-id/.
#   - SIM insertada y registrada en la red.
#
# Uso:
#   provision-modem.sh \
#     --imei 868090012345678 \
#     --iccid 8937012345678901234 \
#     --serial-port /dev/ttyUSB42 \
#     --operator "Bite Lithuania" \
#     --country LT \
#     --e164 +37061234567 \
#     --model EG25-G \
#     [--max-accounts-per-day 3] \
#     [--max-streams-per-day 250] \
#     [--rotation-cooldown-seconds 90] \
#     [--use-cooldown-seconds 300] \
#     [--notes "Rack 1 slot 12"] \
#     [--dry-run]
#
# El script:
#   1. Valida formato de IMEI / ICCID / E164 / country.
#   2. Verifica conectividad AT al puerto serie (responde ATI).
#   3. Captura el MNC/MCC y firmware del modem para auditoria.
#   4. Inserta en `farm_modems` (tabla local del SMS hub si la BD
#      del hub existe) y en `modems` (control plane DB).
#   5. Logs todo a /var/log/streaming-bot-farm/provisions.log.
#
# Variables de entorno requeridas:
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB (control plane)
#   FARM_DB_URL (opcional; URL Postgres del SMS hub local si distinto)
#   FARM_HOST_DOCKER (opcional; nombre del docker postgres farm)

set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/streaming-bot/infra/compose/.env}"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
fi

REQUIRED_VARS=(POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB)
for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "[provision-modem] ERROR: variable '${var}' no esta seteada" >&2
    exit 64
  fi
done

POSTGRES_HOST="${POSTGRES_HOST:-10.10.0.20}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres}"
LOG_FILE="${LOG_FILE:-/var/log/streaming-bot-farm/provisions.log}"

mkdir -p "$(dirname "${LOG_FILE}")"

# ── Defaults ────────────────────────────────────────────────────────
IMEI=""
ICCID=""
SERIAL_PORT=""
OPERATOR=""
COUNTRY=""
E164=""
MODEL="EG25-G"
MAX_ACCOUNTS_PER_DAY=3
MAX_STREAMS_PER_DAY=250
ROTATION_COOLDOWN_SECONDS=90
USE_COOLDOWN_SECONDS=300
NOTES=""
DRY_RUN=false

# ── Parsing args ────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
  case "$1" in
    --imei) IMEI="$2"; shift 2 ;;
    --iccid) ICCID="$2"; shift 2 ;;
    --serial-port) SERIAL_PORT="$2"; shift 2 ;;
    --operator) OPERATOR="$2"; shift 2 ;;
    --country) COUNTRY="$2"; shift 2 ;;
    --e164) E164="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --max-accounts-per-day) MAX_ACCOUNTS_PER_DAY="$2"; shift 2 ;;
    --max-streams-per-day) MAX_STREAMS_PER_DAY="$2"; shift 2 ;;
    --rotation-cooldown-seconds) ROTATION_COOLDOWN_SECONDS="$2"; shift 2 ;;
    --use-cooldown-seconds) USE_COOLDOWN_SECONDS="$2"; shift 2 ;;
    --notes) NOTES="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help)
      head -n 40 "$0" | grep -E '^#' | sed 's/^# //;s/^#//'
      exit 0 ;;
    *)
      echo "[provision-modem] argumento desconocido: $1" >&2
      exit 64 ;;
  esac
done

# ── Validacion de inputs requeridos ────────────────────────────────

REQUIRED_ARGS=(IMEI ICCID SERIAL_PORT OPERATOR COUNTRY E164)
for arg in "${REQUIRED_ARGS[@]}"; do
  if [[ -z "${!arg}" ]]; then
    echo "[provision-modem] ERROR: argumento --${arg,,} requerido" >&2
    exit 64
  fi
done

# IMEI: 14 o 15 digitos numericos
if [[ ! "${IMEI}" =~ ^[0-9]{14,15}$ ]]; then
  echo "[provision-modem] ERROR: IMEI '${IMEI}' invalido (esperado 14-15 digitos)" >&2
  exit 65
fi

# ICCID: 18-22 digitos numericos
if [[ ! "${ICCID}" =~ ^[0-9]{18,22}$ ]]; then
  echo "[provision-modem] ERROR: ICCID '${ICCID}' invalido (esperado 18-22 digitos)" >&2
  exit 65
fi

# E164: + seguido de 7-15 digitos
if [[ ! "${E164}" =~ ^\+[0-9]{7,15}$ ]]; then
  echo "[provision-modem] ERROR: E164 '${E164}' invalido (esperado formato +CCNNNNNN)" >&2
  exit 65
fi

# country: ISO alpha-2 mayusculas
if [[ ! "${COUNTRY}" =~ ^[A-Z]{2}$ ]]; then
  echo "[provision-modem] ERROR: country '${COUNTRY}' invalido (esperado ISO alpha-2 ej LT, BG, VN)" >&2
  exit 65
fi

# Serial port: existe?
if [[ "${DRY_RUN}" != true && ! -e "${SERIAL_PORT}" ]]; then
  echo "[provision-modem] ERROR: serial port '${SERIAL_PORT}' no existe" >&2
  exit 66
fi

log() {
  local msg="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [provision-modem] $*"
  echo "${msg}" | tee -a "${LOG_FILE}"
}

# ── Smoke test AT command (skip si dry-run) ────────────────────────

ATI_OUTPUT="dry-run-skip"
FIRMWARE_REVISION=""
MNC_MCC=""

if [[ "${DRY_RUN}" != true ]]; then
  if command -v atinout >/dev/null 2>&1; then
    log "ejecutando AT smoke test en ${SERIAL_PORT}"
    if ATI_OUTPUT="$(timeout 10 atinout - "${SERIAL_PORT}" - <<<"ATI" 2>&1)"; then
      log "ATI output: $(echo "${ATI_OUTPUT}" | tr '\n' '|')"
      FIRMWARE_REVISION="$(echo "${ATI_OUTPUT}" | grep -i revision | head -1 | tr -d '\r' || true)"
    else
      log "WARNING: AT smoke test fallo, continuando provisioning con notes flag"
      NOTES="${NOTES} [WARN: AT smoke test failed]"
    fi

    # Captura MCC+MNC (operator code)
    if MCC_OUTPUT="$(timeout 10 atinout - "${SERIAL_PORT}" - <<<'AT+COPS?' 2>&1)"; then
      MNC_MCC="$(echo "${MCC_OUTPUT}" | grep -oP '\+COPS:\s*\d+,\d+,"[^"]*",\d+' | head -1 || true)"
      log "operator: ${MNC_MCC}"
    fi
  else
    log "WARNING: 'atinout' no instalado, omitiendo AT smoke test"
  fi
fi

# ── Generar UUID modem ──────────────────────────────────────────────

if command -v uuidgen >/dev/null 2>&1; then
  MODEM_ID="$(uuidgen)"
else
  MODEM_ID="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || \
              python3 -c 'import uuid; print(uuid.uuid4())')"
fi
log "modem_id generado: ${MODEM_ID}"

# ── SQL inserts ─────────────────────────────────────────────────────

# Construye notes finales
FULL_NOTES="${NOTES}"
if [[ -n "${FIRMWARE_REVISION}" ]]; then
  FULL_NOTES="${FULL_NOTES} fw='${FIRMWARE_REVISION}'"
fi
if [[ -n "${MNC_MCC}" ]]; then
  FULL_NOTES="${FULL_NOTES} cops='${MNC_MCC}'"
fi
FULL_NOTES="$(echo "${FULL_NOTES}" | sed "s/'/''/g")"  # SQL escape single quotes

INSERT_CONTROL_SQL="INSERT INTO modems (
  id, imei, iccid, model, serial_port, operator, sim_country,
  state, max_accounts_per_day, max_streams_per_day,
  rotation_cooldown_seconds, use_cooldown_seconds, notes,
  created_at, updated_at
) VALUES (
  '${MODEM_ID}', '${IMEI}', '${ICCID}', '${MODEL}', '${SERIAL_PORT}',
  '$(echo "${OPERATOR}" | sed "s/'/''/g")', '${COUNTRY}',
  'ready', ${MAX_ACCOUNTS_PER_DAY}, ${MAX_STREAMS_PER_DAY},
  ${ROTATION_COOLDOWN_SECONDS}, ${USE_COOLDOWN_SECONDS}, '${FULL_NOTES}',
  NOW(), NOW()
);"

INSERT_FARM_SQL="INSERT INTO farm_modems (
  imei, iccid, operator, country, e164, serial_port, last_seen_at, flagged_count
) VALUES (
  '${IMEI}', '${ICCID}',
  '$(echo "${OPERATOR}" | sed "s/'/''/g")',
  '${COUNTRY}', '${E164}', '${SERIAL_PORT}', NULL, 0
) ON CONFLICT (imei) DO NOTHING;"

if [[ "${DRY_RUN}" == true ]]; then
  log "DRY RUN - SQL que se ejecutaria:"
  echo "${INSERT_CONTROL_SQL}"
  echo "${INSERT_FARM_SQL}"
  exit 0
fi

# ── Ejecucion control plane (modems table) ─────────────────────────

log "insertando en control plane modems table"
PGPASSWORD="${POSTGRES_PASSWORD}" psql \
  -h "${POSTGRES_HOST}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  -c "${INSERT_CONTROL_SQL}" \
  || {
    log "ERROR: insert en modems control plane fallo (probablemente IMEI duplicado)"
    exit 70
  }

# ── Ejecucion farm SMS hub (farm_modems table) ─────────────────────

# El SMS hub puede correr local en este host (mismo Postgres si
# misma DB) o tener su propia DB en farm_${COUNTRY}. Detectar via
# FARM_DB_URL.

if [[ -n "${FARM_DB_URL:-}" ]]; then
  log "insertando en farm SMS hub DB ${FARM_DB_URL%%@*}@..."
  if command -v psql >/dev/null 2>&1; then
    psql "${FARM_DB_URL}" -c "${INSERT_FARM_SQL}" \
      || log "WARNING: insert en farm_modems fallo"
  else
    log "WARNING: psql no instalado, omitiendo insert en farm_modems"
  fi
else
  log "FARM_DB_URL no seteada; asumiendo farm_modems vive en misma DB control"
  PGPASSWORD="${POSTGRES_PASSWORD}" psql \
    -h "${POSTGRES_HOST}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    -c "${INSERT_FARM_SQL}" \
    || log "WARNING: insert en farm_modems fallo (puede no existir tabla)"
fi

# ── Confirmacion final ──────────────────────────────────────────────

log "modem provisioned: id=${MODEM_ID} imei=${IMEI} country=${COUNTRY} port=${SERIAL_PORT}"

if [[ -n "${TELEGRAM_TOKEN:-}" && -n "${TELEGRAM_CHAT:-}" ]]; then
  curl -fsS "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT}" \
    -d "text=Modem provisioned: ${COUNTRY}/${IMEI}/${OPERATOR} (${MODEL})" \
    || true
fi

cat <<EOM
================================================================
MODEM PROVISIONED
================================================================
Modem ID:         ${MODEM_ID}
IMEI:             ${IMEI}
ICCID:            ${ICCID}
Model:            ${MODEL}
Country:          ${COUNTRY}
Operator:         ${OPERATOR}
E164:             ${E164}
Serial port:      ${SERIAL_PORT}
Max accts/day:    ${MAX_ACCOUNTS_PER_DAY}
Max streams/day:  ${MAX_STREAMS_PER_DAY}
================================================================
EOM

exit 0
