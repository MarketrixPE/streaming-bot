# Operaciones diarias granja — checklist operativo

> Ejecutado cada dia por el operador o tecnico ops de turno.
> Tiempo total target: 30-45 min/dia para una granja de 300
> modems en regimen.

## Setup operador

```sh
# Sesion bastion via SSH a control plane
ssh -p 2222 ops@bastion.<entity-domain>

# Variables comunes en sesion
export INCIDENT_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export PG="docker exec -i -e PGPASSWORD=${POSTGRES_PASSWORD} postgres"
```

## 1. Health checks (5 min)

### 1.1 Grafana dashboards a revisar

> Acceso: <https://grafana.<entity-domain>/d/farm-overview>.

Dashboards obligatorios al inicio del dia:

```
[ ] Farm Overview          - Modems online vs total, breakdown por pais
[ ] SMS Hub Health         - latencia /numbers/rent, SMS recibidos /h
[ ] Modem IP Distribution  - IPs unicas servidas en 24h por modem
[ ] Account Health by IP   - Account state pivot por IP-cluster
[ ] Worker Pool            - Workers activos, queue depth Temporal
[ ] Cost per stream        - costo all-in / streams monetizables (target < $0.0008)
```

### 1.2 Heartbeat critico

```sh
# Ping a todas las locaciones via WireGuard
for FARM in lt bg vn; do
  printf "[farm-%s] " "${FARM}"
  if ping -c 1 -W 5 "farm-${FARM}.<entity-domain>" >/dev/null 2>&1; then
    printf "ALIVE\n"
  else
    printf "DOWN -- TRIGGER DR-5\n"
  fi
done

# Salud SMS hub por farm
for FARM in lt bg vn; do
  curl -fsS --max-time 5 \
    "https://farm-${FARM}.<entity-domain>/healthz" \
    -H "Authorization: Bearer ${SMS_HUB_TOKEN}" \
    && echo " <- farm-${FARM} SMS hub ok" \
    || echo " !! farm-${FARM} SMS hub DOWN"
done
```

## 2. Modem fleet status (5 min)

```sh
# Counts por estado (target: ready > 95%)
$PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
SELECT sim_country, state, COUNT(*) AS n
FROM modems
GROUP BY sim_country, state
ORDER BY sim_country, state;
"

# Modems con flagged_count > 5 (candidatos a SIM rotation o reemplazo fisico)
$PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
SELECT id, imei, sim_country, flagged_count, last_used_at, notes
FROM modems
WHERE flagged_count > 5
ORDER BY flagged_count DESC, last_used_at DESC;
"

# Modems sin actividad en 24h (posibles muertos hardware o stuck)
$PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
SELECT id, imei, sim_country, state, last_used_at
FROM modems
WHERE state='ready'
  AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL '24 hours')
ORDER BY last_used_at NULLS FIRST;
"
```

> Si > 5% de modems aparecen "stuck": ejecutar sequence:
> 1. Revisar troubleshooting.md issue "modem stuck" antes de
>    reiniciar ciegamente.
> 2. Restart del daemon sms-hub-modem@ttyUSBN del modem afectado:
>    ```
>    ssh root@farm-${FARM}.<entity-domain> \
>      'systemctl restart sms-hub-modem@ttyUSB42.service'
>    ```

## 3. SIM data quota reconciliation (5 min)

> Cada SIM tiene un cap mensual (Bite 100 GB, A1 30 GB,
> Viettel 60 GB). Si un modem agota su cap a mitad de mes
> queda offline hasta el reset. Anticipar via reconciliation
> diaria.

```sh
# Estimacion uso mensual por modem (basado en stream_history bytes
# transferidos, asumiendo ~ 4 MB/min Spotify Premium high quality)
$PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
WITH modem_usage AS (
  SELECT
    sr.modem_id,
    SUM(sh.listen_seconds) / 60.0 AS minutes_streamed,
    SUM(sh.listen_seconds) * (4 * 1024 * 1024 / 60.0) AS bytes_estimated
  FROM stream_history sh
  JOIN session_records sr ON sr.id = sh.session_id
  WHERE sh.started_at > date_trunc('month', NOW())
  GROUP BY sr.modem_id
)
SELECT
  m.imei, m.sim_country,
  ROUND(mu.bytes_estimated / 1024 / 1024 / 1024, 2) AS gb_used_mtd,
  CASE
    WHEN m.sim_country='LT' THEN 100
    WHEN m.sim_country='BG' THEN 30
    WHEN m.sim_country='VN' THEN 60
    ELSE 50
  END AS gb_cap,
  ROUND(100.0 * mu.bytes_estimated / 1024 / 1024 / 1024 /
        CASE
          WHEN m.sim_country='LT' THEN 100
          WHEN m.sim_country='BG' THEN 30
          WHEN m.sim_country='VN' THEN 60
          ELSE 50
        END, 1) AS pct_cap
FROM modems m
JOIN modem_usage mu ON mu.modem_id = m.id
WHERE m.state='ready'
ORDER BY pct_cap DESC NULLS LAST
LIMIT 20;
"
```

> Si algun modem > 80% del cap a mitad de mes: throttle el modem
> en `modems.max_streams_per_day` para distribuir uso restante.

## 4. SIM rotation flagged (5 min)

```sh
# Ejecutar el script automatico que detecta SIMs con flagged_count > 5
# y muestra alert para reemplazo fisico
/opt/streaming-bot/infra/scripts/farm/rotate-flagged-sim.sh

# Output esperado:
#   - Lista de SIMs candidatas a reemplazo (con IMEI, ICCID, country, flagged_count)
#   - Telegram notification con resumen
```

## 5. Replace de modems con flagged_count > 5 (10 min decision, work in batches)

> Reemplazo fisico requiere visita on-site. NO improvisar; mantener
> queue de reemplazos a ejecutar en visita semanal/mensual del
> tecnico in-situ.

```sh
# Generar batch reemplazo semanal
$PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
SELECT
  m.id,
  m.imei,
  m.iccid,
  m.serial_port,
  m.sim_country,
  m.flagged_count,
  m.notes
FROM modems m
WHERE m.flagged_count > 5
  AND (m.notes IS NULL OR m.notes NOT ILIKE '%queued for replacement%')
ORDER BY m.sim_country, m.flagged_count DESC;
" > /tmp/replacement-queue-$(date -u +%Y%m%d).tsv

# Marcar como queued (evitar re-listar al dia siguiente)
$PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
UPDATE modems SET notes = COALESCE(notes,'') || E'\nqueued for replacement '||CURRENT_DATE
WHERE flagged_count > 5
  AND (notes IS NULL OR notes NOT ILIKE '%queued for replacement%');
"

# Send batch al tecnico in-situ correspondiente via PGP-encrypted email
# (manual del operador, NO auto-email para evitar leak)
```

## 6. Validacion alertas dia anterior (5 min)

```sh
# Revisar Alertmanager: alertas resueltas vs pending
curl -fsS http://10.10.0.20:9093/api/v2/alerts \
  | jq '.[] | select(.status.state=="active") | {labels, startsAt, generatorURL}' \
  | head -50

# Revisar Telegram dr-ops thread (manual): cualquier alerta sin ack
```

## 7. Ramp-up / ramp-down decisions (5 min)

```sh
# Modems con margen para mas trafico (<60% de utilizacion vs su cap)
$PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
SELECT
  id, imei, sim_country,
  streams_served_today,
  max_streams_per_day,
  ROUND(100.0 * streams_served_today / NULLIF(max_streams_per_day,0), 1) AS pct_util
FROM modems
WHERE state='ready' AND streams_served_today < (max_streams_per_day * 0.6)
ORDER BY pct_util ASC
LIMIT 30;
"

# Modems saturados (>= 90% util) - candidate para increase max_streams_per_day
# si flagged_count==0 y health > 30 dias estable
$PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
SELECT
  id, imei, sim_country,
  streams_served_today, max_streams_per_day, flagged_count,
  AGE(NOW(), created_at) AS age
FROM modems
WHERE state='ready'
  AND streams_served_today >= (max_streams_per_day * 0.9)
  AND flagged_count = 0
  AND created_at < NOW() - INTERVAL '30 days'
LIMIT 30;
"
```

## 8. Reporte rapido fin de dia (5 min)

```sh
# Generar el daily summary y postearlo al canal ops
DATE=$(date -u +%Y-%m-%d)
TOTAL_MODEMS=$($PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c \
  "SELECT COUNT(*) FROM modems")
ONLINE_MODEMS=$($PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c \
  "SELECT COUNT(*) FROM modems WHERE state='ready' AND last_used_at > NOW() - INTERVAL '4 hours'")
FLAGGED=$($PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c \
  "SELECT COUNT(*) FROM modems WHERE flagged_count > 5")
STREAMS_24H=$($PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c \
  "SELECT COUNT(*) FROM stream_history WHERE started_at > NOW() - INTERVAL '24 hours'")
BANS_24H=$($PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c \
  "SELECT COUNT(*) FROM accounts WHERE state='banned' AND banned_at > NOW() - INTERVAL '24 hours'")

cat <<EOM | curl -fsS "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
   -d "chat_id=${TELEGRAM_CHAT}" --data-urlencode "text@-"
Daily Ops Summary ${DATE}
========================
Modems totales: ${TOTAL_MODEMS}
Modems online (4h): ${ONLINE_MODEMS} ($(( 100*ONLINE_MODEMS/TOTAL_MODEMS ))%)
Modems flagged>5: ${FLAGGED}
Streams 24h: ${STREAMS_24H}
Bans 24h: ${BANS_24H}
EOM
```

## Procedimiento semanal (ejecutar lunes)

```
[ ] Revisar Bites/A1/Viettel facturacion (anomalia? consumo > esperado?)
[ ] Revisar reporte de scaling-playbook.md (Mes vs target)
[ ] Validar backups DR exitosos los ultimos 7 dias (ls -la /var/lib/streaming-bot/dr/)
[ ] Validar que rotate-flagged-sim.sh corrio cada dia (cron logs)
[ ] Revisar costos colo en MTD vs presupuesto
[ ] Update postmortems pending action items (si aplica)
[ ] Plan visita on-site del proximo mes (modems a reemplazar, hardware spare)
```

## Procedimiento mensual (primer dia del mes)

```
[ ] Reset de contadores diarios:
    $PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
      UPDATE modems SET accounts_used_today=0, streams_served_today=0;
    "
[ ] Reset de cap reconciliation (mes nuevo, SIM caps reset)
[ ] Reporte scaling-playbook.md (Mes anterior cerrado)
[ ] Pago colo y SIMs (verificar cuenta local de la shell company)
[ ] Reporte de Costo per stream monetizable (target < $0.0008)
[ ] Audit log scan: cualquier patron extrano? (vease compartmentalization.md trim audit)
```

## Reglas DURAS dia a dia

1. NUNCA hacer `UPDATE modems` sin WHERE clause restrictivo o sin
   `BEGIN; ... ROLLBACK;` previo.
2. NUNCA reiniciar 50+ modems simultaneamente; restartar en
   batches de 5-10 con sleep 30s entre batches para no caer la
   USB power supply ni saturar el SMS hub.
3. NUNCA ejecutar `provision-modem.sh` para un IMEI ya registrado
   (idempotencia: el script falla con UNIQUE constraint si ya
   existe).
4. NUNCA postear info especifica (IMEI, ICCID, IP) en Telegram en
   plain text; usar PGP-encrypted email para detalles especificos
   por OPSEC.
5. NUNCA dejar abierto el dashboard Grafana en pantalla de
   computadora compartida o en proyector visible desde camara.
6. NUNCA hacer cambios criticos (provision, rotate, decommission)
   con > 30 modems afectados en 1 hora sin segundo operador
   confirmando.
