#!/usr/bin/env bash
# health-snapshot.sh
#
# Captura snapshot horario de salud del sistema:
#   - Prometheus query exports (KPIs operativos clave)
#   - Grafana dashboard JSON exports (todas las dashboards)
#   - Postgres counts por tabla critica
#   - ClickHouse counts por tabla
#   - Estado granja (modems online vs total)
#   - Estado workers (Temporal taskqueue depths)
#
# Cron sugerido: 0 * * * *  /opt/streaming-bot/infra/scripts/dr/health-snapshot.sh
#
# Output: JSON en MinIO bucket dr/health/{YYYY/MM/DD}/snapshot-{TS}.json
# Retencion: 30 dias rolling (lifecycle policy MinIO).
#
# Variables requeridas:
#   PROMETHEUS_URL (default http://10.10.0.20:9090)
#   GRAFANA_URL (default http://10.10.0.20:3000)
#   GRAFANA_TOKEN (Grafana API key con read access)
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
#   CLICKHOUSE_USER, CLICKHOUSE_PASSWORD, CLICKHOUSE_DB

set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/streaming-bot/infra/compose/.env}"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
fi

REQUIRED_VARS=(POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB CLICKHOUSE_USER CLICKHOUSE_PASSWORD CLICKHOUSE_DB)
for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "[health-snapshot] ERROR: variable '${var}' no esta seteada" >&2
    exit 64
  fi
done

PROMETHEUS_URL="${PROMETHEUS_URL:-http://10.10.0.20:9090}"
GRAFANA_URL="${GRAFANA_URL:-http://10.10.0.20:3000}"
GRAFANA_TOKEN="${GRAFANA_TOKEN:-}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres}"
CLICKHOUSE_CONTAINER="${CLICKHOUSE_CONTAINER:-clickhouse}"
LOCAL_DIR="${LOCAL_DIR:-/var/lib/streaming-bot/dr/health}"
MINIO_ALIAS="${MINIO_ALIAS:-minio}"
LOG_FILE="${LOG_FILE:-/var/log/streaming-bot-dr/health-snapshot.log}"

mkdir -p "${LOCAL_DIR}" "$(dirname "${LOG_FILE}")"
exec >>"${LOG_FILE}" 2>&1

TS="$(date -u +%Y%m%dT%H%M%SZ)"
DATE_PATH="$(date -u +%Y/%m/%d)"
OUTPUT_FILE="${LOCAL_DIR}/snapshot-${TS}.json"

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [health-snapshot] $*"
}

# ── Helpers ─────────────────────────────────────────────────────────

prom_query() {
  local query="$1"
  curl -fsS --max-time 10 \
    --data-urlencode "query=${query}" \
    "${PROMETHEUS_URL}/api/v1/query" 2>/dev/null \
    | jq -c '.data.result' 2>/dev/null \
    || echo "null"
}

pg_count() {
  local table="$1"
  PGPASSWORD="${POSTGRES_PASSWORD}" docker exec -i \
    -e PGPASSWORD="${POSTGRES_PASSWORD}" "${POSTGRES_CONTAINER}" \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At \
    -c "SELECT COUNT(*) FROM ${table}" 2>/dev/null \
    || echo "-1"
}

ch_count() {
  local table="$1"
  docker exec "${CLICKHOUSE_CONTAINER}" clickhouse-client \
    --user "${CLICKHOUSE_USER}" \
    --password "${CLICKHOUSE_PASSWORD}" \
    --database "${CLICKHOUSE_DB}" \
    --query "SELECT COUNT(*) FROM ${table}" 2>/dev/null \
    || echo "-1"
}

# ── Prometheus queries ──────────────────────────────────────────────

log "capturando metrics Prometheus"

PROM_DATA="$(jq -n \
  --argjson up_nodes      "$(prom_query 'up{job="node"}')" \
  --argjson active_streams "$(prom_query 'streaming_bot_active_sessions')" \
  --argjson stream_rate   "$(prom_query 'rate(streaming_bot_streams_total[5m])')" \
  --argjson errors_5m     "$(prom_query 'rate(streaming_bot_errors_total[5m])')" \
  --argjson account_state "$(prom_query 'streaming_bot_accounts_by_state')" \
  --argjson workflow_open "$(prom_query 'temporal_workflow_open_total')" \
  --argjson modem_state   "$(prom_query 'streaming_bot_modems_by_state')" \
  --argjson redis_clients "$(prom_query 'redis_connected_clients')" \
  --argjson pg_replication_lag "$(prom_query 'pg_replication_lag_seconds')" \
  '{
     up_nodes: $up_nodes,
     active_streams: $active_streams,
     stream_rate_5m: $stream_rate,
     errors_5m: $errors_5m,
     account_state_breakdown: $account_state,
     workflow_open_total: $workflow_open,
     modem_state_breakdown: $modem_state,
     redis_clients: $redis_clients,
     pg_replication_lag: $pg_replication_lag
   }')"

# ── Postgres counts ─────────────────────────────────────────────────

log "capturando counts Postgres"

PG_DATA="$(jq -n \
  --arg accounts        "$(pg_count accounts)" \
  --arg songs           "$(pg_count songs)" \
  --arg playlists       "$(pg_count playlists)" \
  --arg modems          "$(pg_count modems)" \
  --arg stream_history  "$(pg_count stream_history)" \
  --arg session_records "$(pg_count session_records)" \
  --arg distributions   "$(pg_count distributions)" \
  --arg campaigns       "$(pg_count campaigns)" \
  '{
     accounts: ($accounts|tonumber),
     songs: ($songs|tonumber),
     playlists: ($playlists|tonumber),
     modems: ($modems|tonumber),
     stream_history: ($stream_history|tonumber),
     session_records: ($session_records|tonumber),
     distributions: ($distributions|tonumber),
     campaigns: ($campaigns|tonumber)
   }')"

# ── Postgres breakdown por estado ───────────────────────────────────

log "capturando breakdown estados"

ACCOUNTS_BY_STATE="$(PGPASSWORD="${POSTGRES_PASSWORD}" docker exec -i \
  -e PGPASSWORD="${POSTGRES_PASSWORD}" "${POSTGRES_CONTAINER}" \
  psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -A -t -F'|' \
  -c "SELECT state, COUNT(*) FROM accounts GROUP BY state" 2>/dev/null \
  | awk -F'|' 'BEGIN{printf "{"; first=1} {if(!first){printf ","} first=0; printf "\"%s\":%s",$1,$2} END{printf "}"}' \
  || echo "{}")"

MODEMS_BY_STATE="$(PGPASSWORD="${POSTGRES_PASSWORD}" docker exec -i \
  -e PGPASSWORD="${POSTGRES_PASSWORD}" "${POSTGRES_CONTAINER}" \
  psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -A -t -F'|' \
  -c "SELECT state, COUNT(*) FROM modems GROUP BY state" 2>/dev/null \
  | awk -F'|' 'BEGIN{printf "{"; first=1} {if(!first){printf ","} first=0; printf "\"%s\":%s",$1,$2} END{printf "}"}' \
  || echo "{}")"

# ── ClickHouse counts ──────────────────────────────────────────────

log "capturando counts ClickHouse"

CH_DATA="$(jq -n \
  --arg events  "$(ch_count events)" \
  --arg metrics "$(ch_count metrics)" \
  '{
     events: ($events|tonumber),
     metrics: ($metrics|tonumber)
   }')"

# ── Disk usage ──────────────────────────────────────────────────────

log "capturando disk usage"

DISK_USAGE="$(df -B1 / | awk 'NR==2 {printf "{\"total\":%s,\"used\":%s,\"avail\":%s,\"pct\":%d}", $2,$3,$4,$5+0}')"

# ── Build snapshot final ────────────────────────────────────────────

jq -n \
  --arg ts "${TS}" \
  --arg hostname "$(hostname)" \
  --argjson prom "${PROM_DATA:-null}" \
  --argjson pg "${PG_DATA:-null}" \
  --argjson accounts_by_state "${ACCOUNTS_BY_STATE:-{}}" \
  --argjson modems_by_state "${MODEMS_BY_STATE:-{}}" \
  --argjson ch "${CH_DATA:-null}" \
  --argjson disk "${DISK_USAGE:-null}" \
  '{
     timestamp: $ts,
     hostname: $hostname,
     prometheus: $prom,
     postgres_counts: $pg,
     accounts_by_state: $accounts_by_state,
     modems_by_state: $modems_by_state,
     clickhouse_counts: $ch,
     disk_usage_root: $disk
   }' > "${OUTPUT_FILE}"

log "snapshot escrito a ${OUTPUT_FILE} ($(wc -c < "${OUTPUT_FILE}") bytes)"

# ── Grafana dashboards (solo cada 24h al snapshot 00:00) ───────────

HOUR="$(date -u +%H)"
if [[ "${HOUR}" == "00" && -n "${GRAFANA_TOKEN}" ]]; then
  log "exportando dashboards Grafana (snapshot 00:00 UTC)"
  GRAFANA_DIR="${LOCAL_DIR}/grafana-${TS}"
  mkdir -p "${GRAFANA_DIR}"

  DASHBOARDS_JSON="$(curl -fsS \
    -H "Authorization: Bearer ${GRAFANA_TOKEN}" \
    "${GRAFANA_URL}/api/search?type=dash-db" || echo "[]")"

  echo "${DASHBOARDS_JSON}" | jq -c '.[] | {uid: .uid, title: .title}' \
    | while read -r dash; do
      uid="$(echo "${dash}" | jq -r '.uid')"
      title="$(echo "${dash}" | jq -r '.title' | tr ' /' '__')"
      curl -fsS \
        -H "Authorization: Bearer ${GRAFANA_TOKEN}" \
        "${GRAFANA_URL}/api/dashboards/uid/${uid}" \
        > "${GRAFANA_DIR}/${title}-${uid}.json" 2>/dev/null \
        || log "WARNING: dashboard ${uid} export fallo"
    done

  if command -v mc >/dev/null 2>&1; then
    mc mirror --overwrite --quiet "${GRAFANA_DIR}/" \
      "${MINIO_ALIAS}/dr/grafana/${DATE_PATH}/${TS}/"
  fi
fi

# ── Subir snapshot a MinIO ──────────────────────────────────────────

if command -v mc >/dev/null 2>&1; then
  log "subiendo snapshot a MinIO ${MINIO_ALIAS}/dr/health/${DATE_PATH}/"
  if ! mc cp --quiet "${OUTPUT_FILE}" \
      "${MINIO_ALIAS}/dr/health/${DATE_PATH}/snapshot-${TS}.json"; then
    log "WARNING: subida MinIO fallo"
  fi
else
  log "WARNING: 'mc' no instalado, snapshot solo localmente"
fi

# ── Limpieza local: mantener 7 dias ────────────────────────────────

find "${LOCAL_DIR}" -maxdepth 1 -type f -name 'snapshot-*.json' -mtime +7 -delete \
  || true
find "${LOCAL_DIR}" -maxdepth 1 -type d -name 'grafana-*' -mtime +14 -exec rm -rf {} + \
  || true

log "completado: snapshot-${TS}.json"
exit 0
