#!/usr/bin/env bash
# rotate-flagged-sim.sh
#
# Detecta SIMs (modems) con flagged_count > umbral y muestra alerta
# para reemplazo fisico.
#
# - Lista los modems candidatos a rotacion fisica de SIM.
# - Marca en `notes` el modem como `queued for replacement` para
#   evitar listar el mismo modem dia tras dia.
# - Quarantine automatico si flagged_count > QUARANTINE_THRESHOLD.
# - Notifica al canal Telegram con summary y batch list a entregar
#   al tecnico in-situ.
#
# Cron sugerido: 0 8 * * * /opt/streaming-bot/infra/scripts/farm/rotate-flagged-sim.sh
#
# Variables de entorno requeridas:
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
# Opcionales:
#   FLAGGED_THRESHOLD (default 5; modems > este valor entran en queue)
#   QUARANTINE_THRESHOLD (default 8; modems > este valor entran en quarantine inmediato)
#   TELEGRAM_TOKEN, TELEGRAM_CHAT (alertas)

set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/streaming-bot/infra/compose/.env}"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
fi

REQUIRED_VARS=(POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB)
for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "[rotate-flagged-sim] ERROR: variable '${var}' no esta seteada" >&2
    exit 64
  fi
done

POSTGRES_HOST="${POSTGRES_HOST:-10.10.0.20}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres}"
FLAGGED_THRESHOLD="${FLAGGED_THRESHOLD:-5}"
QUARANTINE_THRESHOLD="${QUARANTINE_THRESHOLD:-8}"
LOG_FILE="${LOG_FILE:-/var/log/streaming-bot-farm/rotate-flagged-sim.log}"
OUTPUT_DIR="${OUTPUT_DIR:-/var/lib/streaming-bot/farm/replacement-queue}"

mkdir -p "$(dirname "${LOG_FILE}")" "${OUTPUT_DIR}"

DATE_TODAY="$(date -u +%Y-%m-%d)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"

log() {
  local msg="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [rotate-flagged-sim] $*"
  echo "${msg}" | tee -a "${LOG_FILE}"
}

# ── Helper psql wrapper ─────────────────────────────────────────────

run_sql() {
  local sql="$1"
  PGPASSWORD="${POSTGRES_PASSWORD}" psql \
    -h "${POSTGRES_HOST}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    -At -F'|' -c "${sql}"
}

run_sql_exec() {
  local sql="$1"
  PGPASSWORD="${POSTGRES_PASSWORD}" psql \
    -h "${POSTGRES_HOST}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    -c "${sql}"
}

# ── 1) Quarantine automatico de modems con flagged > QUARANTINE_THRESHOLD

log "fase 1: quarantine modems con flagged_count > ${QUARANTINE_THRESHOLD}"

QUARANTINE_SQL="UPDATE modems
SET state = 'quarantined',
    notes = COALESCE(notes,'') || E'\nauto-quarantine ${TS} flagged>${QUARANTINE_THRESHOLD}',
    updated_at = NOW()
WHERE flagged_count > ${QUARANTINE_THRESHOLD}
  AND state != 'quarantined'
RETURNING id, imei, sim_country, flagged_count;"

QUARANTINED="$(run_sql "${QUARANTINE_SQL}" || true)"
QUARANTINED_COUNT=$(echo "${QUARANTINED}" | grep -c '^.' || true)

if [[ "${QUARANTINED_COUNT}" -gt 0 ]]; then
  log "quarantined ${QUARANTINED_COUNT} modems automaticamente:"
  echo "${QUARANTINED}" | tee -a "${LOG_FILE}"
fi

# ── 2) Listar candidatos a rotacion (flagged entre threshold y quarantine)

log "fase 2: listar modems con flagged_count entre ${FLAGGED_THRESHOLD} y ${QUARANTINE_THRESHOLD}"

CANDIDATES_SQL="SELECT
  id,
  imei,
  iccid,
  sim_country,
  operator,
  serial_port,
  flagged_count,
  state,
  COALESCE(notes,'') AS notes
FROM modems
WHERE flagged_count > ${FLAGGED_THRESHOLD}
  AND flagged_count <= ${QUARANTINE_THRESHOLD}
  AND state IN ('ready','idle','rotating')
  AND (notes IS NULL OR notes NOT ILIKE '%queued for replacement%')
ORDER BY sim_country, flagged_count DESC;"

CANDIDATES="$(run_sql "${CANDIDATES_SQL}" || true)"
CANDIDATES_COUNT=$(echo "${CANDIDATES}" | grep -c '^.' || true)

if [[ "${CANDIDATES_COUNT}" -eq 0 ]]; then
  log "ningun modem nuevo candidato a rotacion fisica"
else
  log "encontrados ${CANDIDATES_COUNT} modems candidatos para rotacion SIM"

  # Persiste el batch como TSV para uso del tecnico in-situ
  BATCH_FILE="${OUTPUT_DIR}/batch-${DATE_TODAY}.tsv"
  {
    echo -e "modem_id\timei\ticcid\tcountry\toperator\tserial_port\tflagged_count\tstate\tnotes"
    echo "${CANDIDATES}" | tr '|' '\t'
  } > "${BATCH_FILE}"
  log "batch persistido en ${BATCH_FILE}"

  # Marca como queued en notes (idempotente)
  MARK_SQL="UPDATE modems
  SET notes = COALESCE(notes,'') || E'\nqueued for replacement ${DATE_TODAY}'
  WHERE flagged_count > ${FLAGGED_THRESHOLD}
    AND flagged_count <= ${QUARANTINE_THRESHOLD}
    AND state IN ('ready','idle','rotating')
    AND (notes IS NULL OR notes NOT ILIKE '%queued for replacement%');"
  run_sql_exec "${MARK_SQL}" >/dev/null
  log "modems marcados con 'queued for replacement ${DATE_TODAY}'"
fi

# ── 3) Reporte agregado por pais ───────────────────────────────────

log "fase 3: reporte agregado por pais"

REPORT_SQL="SELECT
  sim_country,
  COUNT(*) FILTER (WHERE state = 'ready') AS ready,
  COUNT(*) FILTER (WHERE state = 'quarantined') AS quarantined,
  COUNT(*) FILTER (WHERE flagged_count > ${FLAGGED_THRESHOLD}) AS flagged_over_threshold,
  COUNT(*) AS total
FROM modems
GROUP BY sim_country
ORDER BY sim_country;"

REPORT="$(run_sql "${REPORT_SQL}" || true)"
log "reporte agregado:"
echo "${REPORT}" | column -s'|' -t | tee -a "${LOG_FILE}"

# ── 4) Notificacion Telegram ───────────────────────────────────────

if [[ -n "${TELEGRAM_TOKEN:-}" && -n "${TELEGRAM_CHAT:-}" ]]; then
  SUMMARY="$(cat <<EOM
Rotate-flagged-SIM run ${DATE_TODAY}

Quarantined automaticamente: ${QUARANTINED_COUNT}
Nuevos candidatos a rotacion: ${CANDIDATES_COUNT}

Reporte agregado por pais:
$(echo "${REPORT}" | column -s'|' -t)

Batch file (envio al tecnico):
${BATCH_FILE:-N/A}
EOM
  )"

  curl -fsS "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT}" \
    --data-urlencode "text=${SUMMARY}" \
    >/dev/null 2>&1 \
    || log "WARNING: notificacion Telegram fallo"

  if [[ "${QUARANTINED_COUNT}" -gt 5 || "${CANDIDATES_COUNT}" -gt 10 ]]; then
    log "ALERTA: spike de modems flagged, considerar incidente DR-3"
    curl -fsS "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
      -d "chat_id=${TELEGRAM_CHAT}" \
      -d "text=ALERTA: ${QUARANTINED_COUNT} quarantined + ${CANDIDATES_COUNT} flagged. Revisar DR-3 (cluster ban)." \
      >/dev/null 2>&1 \
      || true
  fi
fi

# ── 5) Limpieza de batch files antiguos (> 90 dias) ────────────────

find "${OUTPUT_DIR}" -maxdepth 1 -type f -name 'batch-*.tsv' -mtime +90 -delete 2>/dev/null || true

log "completado ts=${TS}"
exit 0
