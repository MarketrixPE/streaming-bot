# Disaster Recovery — escenarios y procedimientos exactos

> Cada escenario sigue el mismo formato: **trigger / detection /
> impact / runbook paso a paso / criterio de cierre**. Los comandos
> son ejecutables tal cual; las variables se leen del entorno
> (`/opt/streaming-bot/infra/compose/.env`).

## Convencion comandos

Asumir, salvo que se indique:

- SSH a `node-control` o `node-data` desde estacion bastion.
- Variables disponibles via `source /opt/streaming-bot/infra/compose/.env`.
- `docker exec` accesible para los contenedores `postgres`,
  `clickhouse`, `redis`, `minio`, `temporal`, `cloudflared`.
- `mc` (MinIO client) configurado con alias `minio` (primario) y
  `b2` (Backblaze backup geografico).
- ID del incidente: `INCIDENT_ID="$(date -u +%Y%m%dT%H%M%SZ)"`,
  carpeta de trabajo: `/var/log/streaming-bot-dr/${INCIDENT_ID}/`.

---

## DR-1 — Hetzner data node down (perdida total node-data)

### Trigger
- Alerta Prometheus `instance_down` para `node-data` > 5 min.
- Hetzner status page reporta incidente en Helsinki.
- SSH timeout a `10.10.0.20`.

### Detection
- Grafana dashboard "Infra heartbeat" muestra rojo.
- Telegram bot `dr-ops` recibe alerta de Alertmanager.

### Impact
- Postgres, ClickHouse, Redis, MinIO, Temporal: OFFLINE.
- Workers en `node-workers` empiezan a fallar (no pueden persistir
  state) en T+1-3 min.
- Dashboard Next.js retorna 502/503.

### Runbook

```sh
# 0. Setup incidente
INCIDENT_ID="$(date -u +%Y%m%dT%H%M%SZ)"
INCIDENT_DIR="/var/log/streaming-bot-dr/${INCIDENT_ID}"
mkdir -p "${INCIDENT_DIR}"
exec > >(tee -a "${INCIDENT_DIR}/timeline.log") 2>&1
echo "[$(date -Iseconds)] DR-1 inicio"

# 1. Confirmar perdida total (no es flap de red)
ping -c 5 10.10.0.20 || echo "node-data unreachable - confirmado"
ssh -o ConnectTimeout=10 root@10.10.0.20 'echo alive' || echo "ssh failed"

# 2. Notificar al canal dr-ops (Telegram via curl)
TELEGRAM_TOKEN="$(cat /etc/streaming-bot/telegram.token)"
TELEGRAM_CHAT="$(cat /etc/streaming-bot/dr-ops.chat)"
curl -s "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT}" \
  -d "text=DR-1 inciado por ${USER}@$(hostname): ${INCIDENT_ID}"

# 3. Pausar workers y kill-switch global preventivo
ssh root@10.10.0.30 'cd /opt/streaming-bot/infra/compose && \
  docker compose -f workers.yml down'

# 4. Provisionar nuevo node-data (Hetzner Server Auction o robot)
#    -- decision manual: aceptar siguiente AX102 disponible en
#       Helsinki (precio target <= EUR 90/mes/server)
cd /opt/streaming-bot/infra/terraform
tofu apply -var="recreate_data_node=true" -var="data_region=hel1" \
  -auto-approve | tee "${INCIDENT_DIR}/terraform.log"

# 5. Recuperar IP del nuevo nodo y configurar DNS interno
NEW_DATA_IP=$(tofu output -raw data_node_ip)
echo "${NEW_DATA_IP} new-node-data" >> "${INCIDENT_DIR}/dns.log"

# 6. Bootstrap nodo + WireGuard mesh con misma IP interna 10.10.0.20
ssh root@${NEW_DATA_IP} \
  'curl -fsSL https://raw.githubusercontent.com/<your-mirror>/streaming-bot/main/infra/scripts/bootstrap-node.sh | bash'

scp /etc/wireguard/peer-data.conf root@${NEW_DATA_IP}:/etc/wireguard/wg0.conf
ssh root@${NEW_DATA_IP} 'systemctl enable --now wg-quick@wg0'

# 7. Restaurar Postgres desde snapshot mas reciente (point in time si hace falta)
ssh root@${NEW_DATA_IP} \
  '/opt/streaming-bot/infra/scripts/dr/restore-postgres.sh latest' \
  | tee "${INCIDENT_DIR}/postgres-restore.log"

# 8. Restaurar ClickHouse
ssh root@${NEW_DATA_IP} \
  '/opt/streaming-bot/infra/scripts/dr/restore-clickhouse.sh latest' \
  | tee "${INCIDENT_DIR}/clickhouse-restore.log"

# 9. Resetear Redis (state volatil aceptable)
ssh root@${NEW_DATA_IP} \
  'cd /opt/streaming-bot/infra/compose && docker compose -f data-plane.yml --env-file .env up -d redis'

# 10. Levantar resto de plano de datos
ssh root@${NEW_DATA_IP} \
  'cd /opt/streaming-bot/infra/compose && docker compose -f data-plane.yml --env-file .env up -d'

# 11. Restaurar Temporal (depende de Postgres ya recuperado)
ssh root@${NEW_DATA_IP} \
  'docker compose -f /opt/streaming-bot/infra/compose/data-plane.yml restart temporal-server'

# 12. Restart workers
ssh root@10.10.0.30 \
  'cd /opt/streaming-bot/infra/compose && docker compose -f workers.yml --env-file .env up -d --scale worker=8'

# 13. Validar end-to-end con sintetico
curl -fsSL https://dashboard.<entity-domain>/api/healthz \
  | tee "${INCIDENT_DIR}/healthz.json"

# 14. Snapshot health post-recovery
/opt/streaming-bot/infra/scripts/dr/health-snapshot.sh \
  > "${INCIDENT_DIR}/health-post.json"

# 15. Cierre
echo "[$(date -Iseconds)] DR-1 cierre" | tee -a "${INCIDENT_DIR}/timeline.log"
curl -s "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT}" \
  -d "text=DR-1 RESUELTO: ${INCIDENT_ID}, RTO=${SECONDS}s"
```

### Criterio de cierre
- `/api/healthz` retorna 200 con `db_ok=true && temporal_ok=true && redis_ok=true`.
- Dashboard Grafana "Infra heartbeat" verde para todos los nodos.
- 1 stream sintetico ejecutado correctamente end-to-end.
- Postmortem iniciado en `${INCIDENT_DIR}/postmortem.md`.

### Tiempo objetivo: 60-90 min (RTO 1h, holgura)

---

## DR-2 — Distribuidor masivo takedown (caso Boomy/DistroKid 2023)

### Trigger
- Email del distribuidor (o cambio de status en API) reporta
  takedown masivo > 10% del catalogo en una sola comunicacion.
- Caso historico real: DistroKid retiro masivo de Boomy en
  2023 [^boomy].

[^boomy]: Variety, "Spotify Pulls Tens of Thousands of Songs From AI Music Generator Boomy" (mayo 2023): <https://variety.com/2023/music/news/spotify-pulls-songs-ai-music-generator-boomy-1235609402/>.

### Detection
- Cron diario que pollea API status de cada distro:
  `/opt/streaming-bot/infra/scripts/distros/status-poll.sh`.
- Alerta si `tracks_status='takedown' COUNT(*) > threshold`.

### Impact
- Tracks delisted: pierde 100% del royalty de los tracks afectados
  desde T+0 hasta re-distribuir.
- Reputacional con DSP: el distro afectado cae en penalty con DSP,
  re-uploads del MISMO track con MISMO ISRC pueden ser bloqueados.
- Cuentas warming sobre esos tracks pierden purpose, impacto
  cascada al ratio metrics.

### Runbook

```sh
INCIDENT_ID="$(date -u +%Y%m%dT%H%M%SZ)"
INCIDENT_DIR="/var/log/streaming-bot-dr/${INCIDENT_ID}"
mkdir -p "${INCIDENT_DIR}"
exec > >(tee -a "${INCIDENT_DIR}/timeline.log") 2>&1
DISTRO="$1"  # ej: distrokid, routenote
echo "[$(date -Iseconds)] DR-2 inicio - distro=${DISTRO}"

# 1. Identificar tracks afectados
docker exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c \
  "SELECT s.id, s.title, s.isrc, s.artist_id, a.alias_name
   FROM songs s
   JOIN distributions d ON d.song_id = s.id
   JOIN artists a ON a.id = s.artist_id
   WHERE d.distributor = '${DISTRO}' AND d.status IN ('takedown', 'delisted')
     AND d.updated_at > NOW() - INTERVAL '24 hours'" \
  > "${INCIDENT_DIR}/affected-tracks.tsv"
echo "Tracks afectados: $(wc -l < "${INCIDENT_DIR}/affected-tracks.tsv")"

# 2. Pausar campaigns para todos esos tracks (kill-switch granular)
docker exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c \
  "UPDATE campaigns
   SET status='paused', paused_reason='dr2-takedown-${INCIDENT_ID}',
       paused_at=NOW()
   WHERE song_id IN (SELECT id FROM songs WHERE id = ANY(\$1::text[]))" \
  -v "$(awk -F'\t' '{printf \"\\\"%s\\\",\", $1}' "${INCIDENT_DIR}/affected-tracks.tsv" | sed 's/,$//')"

# 3. Computar % revenue mensual afectado (estimacion)
docker exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c \
  "SELECT ROUND(100.0 * SUM(rev_estimated_30d_usd) / NULLIF(
     (SELECT SUM(rev_estimated_30d_usd) FROM song_revenue_estimates), 0),2) AS pct_revenue
   FROM song_revenue_estimates
   WHERE song_id IN (SELECT s.id FROM songs s JOIN distributions d ON d.song_id=s.id
                     WHERE d.distributor='${DISTRO}' AND d.status='takedown')" \
  | tee "${INCIDENT_DIR}/revenue-impact.txt"

# 4. Alert + decision: si > 25% revenue afectado, escalada burn-down de aliases
PCT=$(cat "${INCIDENT_DIR}/revenue-impact.txt")
if (( $(echo "${PCT} > 25" | bc -l) )); then
  echo "ALERTA: > 25% revenue afectado, evaluar burn-down aliases"
  curl -s "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT}" \
    -d "text=DR-2 ESCALADA: ${PCT}% revenue afectado en ${DISTRO}, burn-down recomendado"
fi

# 5. Re-distribuir a distros sanos (rotacion de aliases)
#    Workflow Temporal: redistribute_after_takedown(song_id, exclude_distro=DISTRO)
for SONG_ID in $(cut -f1 "${INCIDENT_DIR}/affected-tracks.tsv"); do
  curl -X POST "http://10.10.0.30:8088/workflow/start" \
    -H "Content-Type: application/json" \
    -d "{\"workflow\":\"redistribute_after_takedown\",
         \"args\":[\"${SONG_ID}\",\"${DISTRO}\"]}" \
    | tee -a "${INCIDENT_DIR}/redistribute.log"
done

# 6. Rotar artist aliases asociados (si confirmaste burn-down)
#    Crea aliases nuevos via alias_resolver y mapea tracks
for ARTIST_ID in $(cut -f4 "${INCIDENT_DIR}/affected-tracks.tsv" | sort -u); do
  curl -X POST "http://10.10.0.30:8088/aliases/rotate" \
    -H "Content-Type: application/json" \
    -d "{\"artist_id\":\"${ARTIST_ID}\",\"reason\":\"dr2-${INCIDENT_ID}\"}" \
    | tee -a "${INCIDENT_DIR}/aliases-rotated.log"
done

# 7. Reasignar campaigns a tracks ya re-distribuidos (los Temporal workflows
#    crean nuevas rows distributions con status='live')
docker exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c \
  "UPDATE campaigns c
   SET status='active', resumed_at=NOW(),
       distribution_id=(SELECT d2.id FROM distributions d2
                        WHERE d2.song_id=c.song_id AND d2.status='live'
                        ORDER BY d2.created_at DESC LIMIT 1)
   WHERE c.paused_reason='dr2-takedown-${INCIDENT_ID}'
     AND EXISTS (SELECT 1 FROM distributions d2
                 WHERE d2.song_id=c.song_id AND d2.status='live'
                 AND d2.distributor != '${DISTRO}')"

# 8. Documentar en postmortem
cp /opt/streaming-bot/docs/runbooks/dr/postmortem-template.md \
  "${INCIDENT_DIR}/postmortem.md"

# 9. Cierre
curl -s "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT}" \
  -d "text=DR-2 RESUELTO: ${INCIDENT_ID}, ${PCT}% revenue redistribuido"
```

### Criterio de cierre
- 100% de tracks afectados con `distributions.status='live'` en al
  menos 1 distro alterno.
- Campaigns reasignadas y activas.
- Postmortem iniciado con root cause hipotesis (cambio TOS distro,
  AI detection, fingerprint metadata, etc.).
- KPI revenue revisado en T+30 dias para confirmar recuperacion.

### Tiempo objetivo: 4-12 horas (depende del numero de tracks; <30 dias para recuperacion plena del royalty pipeline)

---

## DR-3 — Spotify ban masivo de cuentas por cluster IP

### Trigger
- Spike en `accounts.state='banned'` > 50 cuentas en 1h.
- Pattern detectado: mismo IP-octet (mismo modem o mismo proxy)
  en > 80% de los baneos.
- Alerta Prometheus `account_ban_rate` > umbral.

### Detection
- Grafana panel "Account health by IP cluster" muestra spike.
- Loki query `{service="account_event"} |= "banned"` con time range
  1h muestra concentracion.

### Impact
- Cuentas banneadas perdidas (no recoverable; nuevo signup con SIM
  rotation requerido).
- Cluster IP completo bajo sospecha por Spotify antifraud, riesgo
  de extension a otros clusters si no se aisla rapido.

### Runbook

```sh
INCIDENT_ID="$(date -u +%Y%m%dT%H%M%SZ)"
INCIDENT_DIR="/var/log/streaming-bot-dr/${INCIDENT_ID}"
mkdir -p "${INCIDENT_DIR}"
exec > >(tee -a "${INCIDENT_DIR}/timeline.log") 2>&1
echo "[$(date -Iseconds)] DR-3 inicio"

# 1. Identificar IPs (modems) culpables
docker exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -F'|' -c \
  "SELECT split_part(proxy_used, '.', 1)||'.'||split_part(proxy_used, '.', 2)||'.'||split_part(proxy_used, '.', 3) AS subnet,
          COUNT(*) AS bans_last_1h
   FROM stream_history sh
   JOIN accounts a ON a.id=sh.account_id
   WHERE a.state='banned' AND a.banned_at > NOW() - INTERVAL '1 hour'
   GROUP BY 1
   HAVING COUNT(*) > 5
   ORDER BY 2 DESC" \
  | tee "${INCIDENT_DIR}/banned-subnets.txt"

# 2. Identificar modems serving esas subnets
SUBNETS=$(cut -d'|' -f1 "${INCIDENT_DIR}/banned-subnets.txt" | tr '\n' ',' | sed 's/,$//')
docker exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -F'|' -c \
  "SELECT id, imei, sim_country, current_public_ip
   FROM modems
   WHERE current_public_ip LIKE ANY (
     SELECT subnet||'.%' FROM (VALUES ('${SUBNETS//,/'),('}')) AS s(subnet))" \
  | tee "${INCIDENT_DIR}/affected-modems.txt"

# 3. Pausar workers que esten asignados a esos modems
for MODEM_ID in $(cut -d'|' -f1 "${INCIDENT_DIR}/affected-modems.txt"); do
  curl -X POST "http://10.10.0.30:8088/modems/${MODEM_ID}/quarantine" \
    -H "Authorization: Bearer ${API_TOKEN}" \
    | tee -a "${INCIDENT_DIR}/modem-quarantine.log"
done

# 4. Forzar IP rotation de los modems (AT command via SMS hub)
for MODEM_IMEI in $(cut -d'|' -f2 "${INCIDENT_DIR}/affected-modems.txt"); do
  curl -X POST "http://farm-${SIM_COUNTRY:-lt}.<entity-domain>/modems/${MODEM_IMEI}/rotate-ip" \
    -H "Authorization: Bearer ${SMS_HUB_TOKEN}" \
    | tee -a "${INCIDENT_DIR}/ip-rotation.log"
  sleep 3
done

# 5. Revisar fingerprint coherence: detectar cuentas con mismo fingerprint
#    hash que las banneadas (riesgo de extension)
docker exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c \
  "SELECT a2.id, a2.username, a2.state
   FROM accounts a1
   JOIN accounts a2 ON a2.fingerprint_hash = a1.fingerprint_hash AND a2.id != a1.id
   WHERE a1.state = 'banned' AND a1.banned_at > NOW() - INTERVAL '1 hour'
     AND a2.state = 'active'" \
  | tee "${INCIDENT_DIR}/at-risk-accounts.txt"

# 6. Retiro preventivo de cuentas con anomaly_score > 0.7 en mismo cluster
docker exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c \
  "UPDATE accounts
   SET state='quarantined', quarantine_reason='dr3-${INCIDENT_ID}'
   WHERE id IN (
     SELECT a.id FROM accounts a
     WHERE a.anomaly_score > 0.7 AND a.state='active'
       AND a.last_proxy_used IN (SELECT current_public_ip FROM modems WHERE id = ANY(\$1::text[]))
   )" \
  -v "$(cut -d'|' -f1 "${INCIDENT_DIR}/affected-modems.txt" | sed 's/.*/\\\"&\\\",/g' | tr -d '\n' | sed 's/,$//')"

# 7. Reanudar workers con modems sanos solamente
ssh root@10.10.0.30 \
  'cd /opt/streaming-bot/infra/compose && docker compose -f workers.yml restart worker'

# 8. Notificar Telegram
curl -s "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT}" \
  -d "text=DR-3 ${INCIDENT_ID}: $(wc -l < "${INCIDENT_DIR}/affected-modems.txt") modems aislados, $(wc -l < "${INCIDENT_DIR}/at-risk-accounts.txt") cuentas en cuarentena preventiva"

# 9. Postmortem
cp /opt/streaming-bot/docs/runbooks/dr/postmortem-template.md \
  "${INCIDENT_DIR}/postmortem.md"
```

### Criterio de cierre
- Modems involucrados con nueva IP confirmada (`SELECT current_public_ip FROM modems WHERE id = ANY(...)`).
- Cuentas quarantined > umbral revisadas: o reactivadas si no hay
  flagged_count nuevo en 24h, o purgadas.
- Tasa de baneo en T+24h vuelve a baseline (<5/h).
- Postmortem identifica root cause (firma de comportamiento, IMEI
  flagged previamente, antifraud signal nuevo).

### Tiempo objetivo: 30-60 min para contencion, 24h para recuperacion completa de cuentas

---

## DR-4 — Banking freeze (institucion congela cuenta operativa)

### Trigger
- Email/notificacion de "compliance review" o "account restricted".
- Tentativa de outgoing wire fallida con error compliance.

### Detection
- Manual (email) o automatico via cron `balance-check.sh` que
  detecta status anomalo en API EMI.

### Impact
- Cobros entrantes pueden seguir; salientes bloqueados.
- Si freeze total: capital atrapado 90-180 dias en peor caso.
- OPEX recurrente (Hetzner, Cloudflare, distros) puede cortarse
  si la cuenta era pagadora.

### Runbook

> Procedimiento detallado en
> `docs/legal/banking-redundancy.md` seccion "Procedimiento
> compliance check / freeze". Resumen de pasos 24-48h:

```sh
INCIDENT_ID="$(date -u +%Y%m%dT%H%M%SZ)"
INCIDENT_DIR="/var/log/streaming-bot-dr/${INCIDENT_ID}"
mkdir -p "${INCIDENT_DIR}"
INSTITUTION="$1"  # ej: wise, mercury, revolut, airwallex
echo "[$(date -Iseconds)] DR-4 inicio - institucion=${INSTITUTION}"

# 0. Documentar evidencia
echo "Captura screenshot del UI/email + numero ticket support" \
  | tee -a "${INCIDENT_DIR}/timeline.log"

# 1. Migrar billing recurrente a backup INMEDIATO
#    Hetzner: login + cambiar payment method a backup card
#    Cloudflare: idem
#    Distros: depende del distro
echo "TODO MANUAL: cambiar payment method en Hetzner/Cloudflare/distros" \
  | tee -a "${INCIDENT_DIR}/timeline.log"

# 2. Si outgoing transfers permitidas: barrida del 90% del saldo
#    en SPLITS para US (< USD 9,500), tickets unicos para EU/UK
#    Ejecutar via API si disponible (Wise / Mercury / Airwallex tienen API publica)
case "${INSTITUTION}" in
  wise)
    /opt/streaming-bot/infra/scripts/banking/wise-sweep.sh \
      --target-account "BACKUP_${INSTITUTION}_ALT" --pct 90 \
      | tee "${INCIDENT_DIR}/sweep.log"
    ;;
  mercury)
    /opt/streaming-bot/infra/scripts/banking/mercury-sweep.sh \
      --target-account "BACKUP_MERCURY_ALT" --pct 90 --split-amount 9000 \
      | tee "${INCIDENT_DIR}/sweep.log"
    ;;
  *)
    echo "Manual sweep required for ${INSTITUTION}" | tee -a "${INCIDENT_DIR}/timeline.log"
    ;;
esac

# 3. Migrar cobros entrantes (distros payout method)
echo "TODO MANUAL: cambiar payout en cada distro afectado" \
  | tee -a "${INCIDENT_DIR}/timeline.log"
echo "  - DistroKid: settings -> payouts" >> "${INCIDENT_DIR}/timeline.log"
echo "  - RouteNote: account -> banking" >> "${INCIDENT_DIR}/timeline.log"
echo "  - Amuse: payments" >> "${INCIDENT_DIR}/timeline.log"
echo "  - Stem: payouts" >> "${INCIDENT_DIR}/timeline.log"
echo "  - TuneCore: settings -> payment" >> "${INCIDENT_DIR}/timeline.log"

# 4. Si saldo congelado total y > USD 50k: convertir a cripto via OTC
#    Vease docs/legal/banking-redundancy.md "Tier 3 cripto on/off ramps"
#    NO automatizable por seguridad: el operador contacta OTC desk
#    via PGP-encrypted email al contacto pre-establecido
echo "Si saldo > USD 50k atrapado: contactar OTC desk pre-aprobado" \
  | tee -a "${INCIDENT_DIR}/timeline.log"

# 5. Engage tax lawyer
echo "Email PGP a tax lawyer en ${ENTITY_JURISDICTION}: requesting formal complaint draft" \
  | tee -a "${INCIDENT_DIR}/timeline.log"

# 6. Notificar Telegram
curl -s "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT}" \
  -d "text=DR-4 ${INCIDENT_ID}: ${INSTITUTION} freeze, accion 24-48h en curso"
```

### Criterio de cierre
- Billing recurrente migrado al 100% (verificar charge exitoso en
  backup en T+72h).
- Cobros entrantes redirigidos al 100% (verificar primer payout a
  backup en proximo ciclo del distro).
- Saldo recuperado (decision T+30: si saldo no liberado, escalar
  con regulador).
- Diversificacion 40/60/3/2 reverificada.

### Tiempo objetivo: 24-48h para contencion operativa; 90-180 dias maximo para resolucion legal del freeze

---

## DR-5 — Granja modems offline (corte fisico en colocation)

### Trigger
- Alerta `farm.modems_online_count` cae > 50% del baseline en < 5 min.
- SSH al farm host falla.
- Email/SMS del proveedor colo notifica corte.

### Detection
- Cron `health-snapshot.sh` cada hora detecta caida.
- Telegram alerta inmediata via Alertmanager.

### Impact
- Capacidad de signup de cuentas reducida (no SMS hub propio).
- Capacidad de streaming reducida (proxies 4G/5G del farm offline).
- Cuentas "warming-in-progress" se pausan automatic.

### Runbook

```sh
INCIDENT_ID="$(date -u +%Y%m%dT%H%M%SZ)"
INCIDENT_DIR="/var/log/streaming-bot-dr/${INCIDENT_ID}"
mkdir -p "${INCIDENT_DIR}"
FARM_LOCATION="$1"  # ej: lithuania, bulgaria, vietnam
echo "[$(date -Iseconds)] DR-5 inicio - farm=${FARM_LOCATION}"

# 1. Confirmar caida (no es flap red)
ping -c 5 farm-${FARM_LOCATION}.<entity-domain> || echo "farm unreachable"

# 2. Marcar todos los modems del farm como offline en DB
docker exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c \
  "UPDATE modems SET state='offline', notes=notes || E'\noffline ${INCIDENT_ID}'
   WHERE sim_country = ANY(SELECT iso2 FROM colos WHERE location='${FARM_LOCATION}')"

# 3. Activar overflow temporal en proveedores externos
#    Set proxy_provider primario a ProxyEmpire mobile en la geo afectada
docker exec redis redis-cli SET "proxy:override:${FARM_LOCATION}" \
  "proxyempire:mobile:${FARM_LOCATION}" EX 86400

# 4. Activar 5SIM overflow para nuevas cuentas durante el outage
docker exec redis redis-cli SET "sms_provider:override" "5sim" EX 86400

# 5. Capacity downgrade: pausar campaigns con tier=tier1 que demanden
#    granja propia (mantener tier2/tier3 con overflow)
docker exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c \
  "UPDATE campaigns SET status='paused', paused_reason='dr5-${INCIDENT_ID}'
   WHERE tier='tier1' AND geo IN (SELECT iso2 FROM colos WHERE location='${FARM_LOCATION}')"

# 6. Telegram alert + notificar al colo provider para ETA recovery
curl -s "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT}" \
  -d "text=DR-5 ${INCIDENT_ID}: farm ${FARM_LOCATION} offline, overflow 5SIM+ProxyEmpire activado"

# 7. Polling del farm hasta recovery
while true; do
  if ping -c 1 -W 5 farm-${FARM_LOCATION}.<entity-domain> >/dev/null 2>&1; then
    echo "[$(date -Iseconds)] farm ${FARM_LOCATION} recovered"
    break
  fi
  sleep 60
done

# 8. Validar modems online post-recovery
ssh root@farm-${FARM_LOCATION}.<entity-domain> \
  'cd /opt/streaming-bot/infra/sms_hub && docker compose ps'

# 9. Re-activar campaigns y desactivar overflow
docker exec redis redis-cli DEL "proxy:override:${FARM_LOCATION}"
docker exec redis redis-cli DEL "sms_provider:override"
docker exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c \
  "UPDATE campaigns SET status='active', resumed_at=NOW()
   WHERE paused_reason='dr5-${INCIDENT_ID}'"

# 10. Postmortem
cp /opt/streaming-bot/docs/runbooks/dr/postmortem-template.md \
  "${INCIDENT_DIR}/postmortem.md"
```

### Criterio de cierre
- Farm host accesible via SSH.
- > 80% de modems en estado `state='ready'`.
- Overflow externo desactivado.
- Campaigns reanudadas.

### Tiempo objetivo: 5-30 min contencion (overflow), recuperacion total en T+ETA del colo (1-12h tipico)

---

## DR-6 — Compromiso credenciales (key leak)

### Trigger
- Detectado leak en GitHub git history (Trufflehog o gitleaks
  scanning).
- SSH key personal pierde control (laptop personal robada).
- Vault token comprometido o auditoria detecta uso anomalo.
- Push notif de provider (1Password / Bitwarden) reportando login
  desde IP no esperada.

### Detection
- gitleaks pre-commit hook activado (proteccion preventiva).
- Cron `audit-vault-access.sh` cada 1h detecta accesos anomalos.
- Sentry events con `auth_failure_pattern`.

### Impact
- Cualquier credencial comprometida puede usarse hasta rotacion.
- Postgres / Redis / Temporal / MinIO accesibles si los secrets
  primarios estan filtrados.
- Cuentas distribuidor / banca pueden estar accesibles via API
  tokens.

### Runbook

```sh
INCIDENT_ID="$(date -u +%Y%m%dT%H%M%SZ)"
INCIDENT_DIR="/var/log/streaming-bot-dr/${INCIDENT_ID}"
mkdir -p "${INCIDENT_DIR}"
echo "[$(date -Iseconds)] DR-6 inicio"

# 1. Kill all sessions activas en services SSO (Better Auth)
docker exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c \
  "DELETE FROM auth_sessions; DELETE FROM auth_refresh_tokens;"

# 2. Rotacion completa de tokens (Postgres, Redis, Temporal, MinIO)
/opt/streaming-bot/infra/scripts/dr/rotate-credentials.sh --all \
  | tee "${INCIDENT_DIR}/rotation.log"

# 3. Rotacion de SSH keys (revocar keys comprometidas)
ssh root@10.10.0.30 \
  'sed -i "/ssh-ed25519 AAAA-COMPROMETIDA/d" /root/.ssh/authorized_keys'
ssh root@10.10.0.40 \
  'sed -i "/ssh-ed25519 AAAA-COMPROMETIDA/d" /root/.ssh/authorized_keys'
ssh root@10.10.0.20 \
  'sed -i "/ssh-ed25519 AAAA-COMPROMETIDA/d" /root/.ssh/authorized_keys'

# 4. Rotacion de WireGuard peer keys (regenerar peer del laptop comprometido)
ssh root@10.10.0.30 \
  '/opt/streaming-bot/infra/wireguard/rotate-peer.sh --peer ops-laptop'

# 5. Rotacion de API tokens externos (CapSolver, 5SIM, ProxyEmpire,
#    distros, banking APIs) - manual via UI de cada provider
echo "TODO MANUAL: rotar tokens en CapSolver, 5SIM, ProxyEmpire, distros, banking" \
  | tee -a "${INCIDENT_DIR}/timeline.log"

# 6. Audit log scan: buscar cualquier accion inesperada en las ultimas 30 dias
docker exec postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c \
  "SELECT actor, action, target, timestamp, ip
   FROM audit_log
   WHERE timestamp > NOW() - INTERVAL '30 days'
     AND (ip NOT IN (SELECT ip FROM allowlist_ips)
          OR actor IN (SELECT username FROM auth_users WHERE deactivated_at IS NULL))
   ORDER BY timestamp DESC" \
  | tee "${INCIDENT_DIR}/audit-anomalies.txt"

# 7. ClickHouse events scan: buscar consultas de exfiltration patterns
docker exec clickhouse clickhouse-client --query \
  "SELECT user, source_ip, query, event_time
   FROM system.query_log
   WHERE event_time > now() - INTERVAL 30 DAY
     AND (query ILIKE '%catalog%export%' OR query ILIKE '%accounts%export%')
   ORDER BY event_time DESC
   FORMAT TabSeparated" \
  | tee "${INCIDENT_DIR}/clickhouse-anomalies.txt"

# 8. MinIO access log scan
mc admin trace --in 30d --error minio \
  | grep -E "GetObject|ListObjects" | head -1000 \
  | tee "${INCIDENT_DIR}/minio-anomalies.txt"

# 9. Si hay evidencia de exfiltracion: triggear burn-down de identity layer
echo "Si exfiltracion confirmada: ver docs/legal/compartmentalization.md - Procedimiento burn down" \
  | tee -a "${INCIDENT_DIR}/timeline.log"

# 10. Telegram alert
curl -s "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT}" \
  -d "text=DR-6 ${INCIDENT_ID}: rotacion credenciales completada, audit log review en curso"

# 11. Postmortem (CRITICA: incluir vector de compromiso)
cp /opt/streaming-bot/docs/runbooks/dr/postmortem-template.md \
  "${INCIDENT_DIR}/postmortem.md"
```

### Criterio de cierre
- TODAS las credenciales rotadas (Vault, SSH, WireGuard, API
  tokens externos).
- Audit log + ClickHouse log + MinIO trace revisados, ningun
  patron sospechoso adicional sin investigar.
- Sessions activas: 0 con tokens previos.
- Si exfiltracion confirmada: burn-down de la capa expuesta
  iniciado.

### Tiempo objetivo: 1-4 horas para rotacion + audit; 24-72h para investigacion completa

---

## Tabla resumen escenarios -> RTO -> impacto revenue maximo aceptable

| Escenario | RTO | Revenue impact maximo aceptable | Frecuencia esperada/ano |
|-----------|-----|----------------------------------|--------------------------|
| DR-1 Hetzner data node down | 1h | <2% | 0-1 |
| DR-2 Distribuidor takedown masivo | 4-12h | <30% | 1-3 |
| DR-3 Spotify ban masivo cluster | 30-60 min | <10% | 3-6 |
| DR-4 Banking freeze | 24-48h | <15% (delayed cashflow) | 0-2 |
| DR-5 Granja offline | 30 min (overflow) - 12h (full recovery) | <5% (overflow active) | 2-4 |
| DR-6 Compromiso credenciales | 1-4h tecnico, 24-72h investigacion | depends on exfil scope | 0-1 |
