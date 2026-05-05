# Dry-run trimestral DR-2 — checklist de simulacro

> Aplica cada trimestre (semanas 13, 26, 39, 52 del calendario
> operativo). El simulacro NO debe afectar produccion en ningun
> caso: usa entornos de staging y datos sinteticos, salvo el paso
> final controlado de "redistribute" que SI se ejecuta sobre 1
> track de muestra real (catalogo low-tier, low-revenue, declarado
> "expendable" para test).

## Objetivo

Medir tres cosas:

1. **% revenue afectado** si DR-2 ocurriera con la composicion
   actual de catalogo + distros.
2. **Time-to-recovery** real desde deteccion hasta tracks
   redistribuidos vivos.
3. **Gaps detectados**: cualquier paso del runbook que falle, este
   ambiguo, o requiera ajuste.

## Pre-requisitos del simulacro

- [ ] Entorno staging accesible (`staging.dashboard.<entity-domain>`).
- [ ] Snapshot reciente de Postgres en staging (< 24h).
- [ ] 1 track marcado en catalogo como `is_dry_run_eligible=true`
  (preferiblemente lifetime royalty < USD 5).
- [ ] Tax lawyer notificado del simulacro (NO ejecucion legal
  necesaria, pero awareness para discriminar de incidente real).
- [ ] Bloque de tiempo reservado: 4 horas continuas, calendario
  fijo.

## Roles

| Rol | Responsable |
|-----|-------------|
| Drill Leader | Operador principal |
| Observer | Operador secundario o contractor de turno (toma timestamps + notes) |
| Postmortem author | Drill Leader (T+24h) |

---

## Checklist Phase 0 — Preparacion (T -1 dia)

```
[ ] Notificar al equipo (canal dr-ops) "Simulacro DR-2 programado para [fecha], NO es real"
[ ] Generar snapshot Postgres staging actualizado:
    /opt/streaming-bot/infra/scripts/dr/snapshot-postgres.sh staging
[ ] Verificar que script restore-postgres.sh corre limpio en staging:
    /opt/streaming-bot/infra/scripts/dr/restore-postgres.sh latest --staging
[ ] Identificar 1 track real "expendable" para test live de redistribute:
    docker exec postgres psql -d streaming_bot -c \
      "SELECT id,title,isrc FROM songs WHERE is_dry_run_eligible=true ORDER BY RANDOM() LIMIT 1"
[ ] Confirmar que distro de origen del track tiene takedown manual disponible (UI funcional)
[ ] Confirmar que distro alterno tiene capacidad de upload manual (UI funcional)
[ ] Reset de variables Telegram para canal dry-run-ops (separado de dr-ops):
    DRY_RUN_TELEGRAM_CHAT="$(cat /etc/streaming-bot/dry-run-ops.chat)"
```

## Checklist Phase 1 — Simulacion deteccion (T 0min - 15min)

```
[ ] Simular email mock: "DistroKid notice - 12% of catalog under review for AI policy violation"
    (NO mandar al distro real; documento local)
[ ] Capturar timestamp T0 = $(date -Iseconds)
[ ] Verificar que cron status-poll detectaria el escenario:
    /opt/streaming-bot/infra/scripts/distros/status-poll.sh --dry-run
[ ] Estimar % catalogo bajo el supuesto "afectado por revision":
    docker exec postgres psql -d streaming_bot -At -c \
      "SELECT ROUND(100.0 * COUNT(DISTINCT s.id) /
              (SELECT COUNT(*) FROM songs WHERE active=true), 2) AS pct
       FROM songs s JOIN distributions d ON d.song_id=s.id
       WHERE d.distributor='distrokid' AND s.active=true"
[ ] Estimar % revenue bajo supuesto:
    docker exec postgres psql -d streaming_bot -At -c \
      "SELECT ROUND(100.0 * SUM(rev_estimated_30d_usd) /
              NULLIF((SELECT SUM(rev_estimated_30d_usd) FROM song_revenue_estimates), 0), 2)
       FROM song_revenue_estimates sre
       JOIN songs s ON s.id=sre.song_id
       JOIN distributions d ON d.song_id=s.id
       WHERE d.distributor='distrokid'"
[ ] Capturar metric% revenue afectado para reporte: ${PCT_REVENUE}
[ ] Notificar canal dry-run-ops con valor calculado
```

## Checklist Phase 2 — Pausa de campaigns (T 15min - 30min)

```
[ ] Capturar lista de campaigns activos pre-pausa:
    docker exec postgres psql -d streaming_bot -At -c \
      "SELECT id, song_id, status FROM campaigns WHERE status='active'" \
      > /tmp/campaigns-pre-${INCIDENT_ID}.tsv
[ ] Pausar SOLO en staging (NO produccion):
    docker exec postgres-staging psql -d streaming_bot_staging -c \
      "UPDATE campaigns SET status='paused', paused_reason='dryrun-${INCIDENT_ID}'
       WHERE song_id IN (SELECT song_id FROM distributions WHERE distributor='distrokid')"
[ ] Capturar count de campaigns pausados:
    docker exec postgres-staging psql -d streaming_bot_staging -At -c \
      "SELECT COUNT(*) FROM campaigns WHERE paused_reason='dryrun-${INCIDENT_ID}'"
[ ] Capturar timestamp T1 = $(date -Iseconds)
```

## Checklist Phase 3 — Identificacion alternativa distros (T 30min - 60min)

```
[ ] Listar tracks que solo viven en distrokid (single-distro risk):
    docker exec postgres psql -d streaming_bot -At -c \
      "SELECT s.id, s.title FROM songs s
       WHERE s.active=true
         AND s.id IN (SELECT song_id FROM distributions WHERE distributor='distrokid')
         AND s.id NOT IN (SELECT song_id FROM distributions
                          WHERE distributor != 'distrokid' AND status='live')" \
      > /tmp/single-distro-${INCIDENT_ID}.tsv
[ ] Capturar count: si > 0, ESO ES UN GAP (deberian tener minimo 2 distros)
[ ] Para cada track multi-distro, identificar distro alterno disponible:
    docker exec postgres psql -d streaming_bot -At -c \
      "SELECT s.id, d.distributor FROM songs s
       JOIN distributions d ON d.song_id=s.id
       WHERE s.id IN (SELECT song_id FROM distributions WHERE distributor='distrokid')
         AND d.distributor != 'distrokid' AND d.status='live'"
[ ] Capturar timestamp T2 = $(date -Iseconds)
```

## Checklist Phase 4 — Test redistribute en staging (T 60min - 120min)

```
[ ] Ejecutar workflow redistribute_after_takedown sobre 1 track real expendable:
    DRY_TRACK_ID="$(docker exec postgres-staging psql -d streaming_bot_staging -At -c \
      "SELECT id FROM songs WHERE is_dry_run_eligible=true LIMIT 1")"
    curl -X POST "http://staging.dashboard.<entity-domain>/api/workflow/start" \
      -H "Authorization: Bearer ${API_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "{\"workflow\":\"redistribute_after_takedown\",
           \"args\":[\"${DRY_TRACK_ID}\",\"distrokid\"]}"
[ ] Verificar que workflow llega a distro_alterno API:
    docker logs temporal-server-staging --tail 100 | grep "${DRY_TRACK_ID}"
[ ] Esperar workflow completion (max 5 min):
    while ! curl -s "http://staging.dashboard.<entity-domain>/api/workflow/status?id=${DRY_TRACK_ID}" \
      | grep -q '"status":"completed"'; do sleep 30; done
[ ] Validar que distribution row nueva existe:
    docker exec postgres-staging psql -d streaming_bot_staging -At -c \
      "SELECT distributor, status FROM distributions WHERE song_id='${DRY_TRACK_ID}'
       ORDER BY created_at DESC LIMIT 5"
[ ] Capturar timestamp T3 = $(date -Iseconds)
```

## Checklist Phase 5 — Validacion campaigns reasignacion (T 120min - 150min)

```
[ ] Validar que campaigns post-redistribute apuntan al distro nuevo:
    docker exec postgres-staging psql -d streaming_bot_staging -At -c \
      "SELECT c.id, c.distribution_id, d.distributor
       FROM campaigns c JOIN distributions d ON d.id=c.distribution_id
       WHERE c.song_id='${DRY_TRACK_ID}' AND c.status='active'"
[ ] Si NO esta apuntando al distro nuevo: GAP en workflow (anotar)
[ ] Restaurar staging al estado pre-simulacro:
    /opt/streaming-bot/infra/scripts/dr/restore-postgres.sh latest --staging
[ ] Capturar timestamp T4 = $(date -Iseconds)
```

## Checklist Phase 6 — Cleanup y reporte (T 150min - 240min)

```
[ ] Confirmar que produccion NO fue afectada:
    docker exec postgres psql -d streaming_bot -At -c \
      "SELECT COUNT(*) FROM campaigns WHERE paused_reason LIKE 'dryrun-%'"
    Result esperado: 0
[ ] Anular el track expendable real si quedo doble-distribuido en
    distros activos (manual via UI cada distro):
    [ ] Login distro alterno usado en test, takedown del DRY_TRACK_ID
[ ] Calcular metricas finales:
    - Time-to-detect = T1 - T0
    - Time-to-pause = T2 - T1
    - Time-to-redistribute = T3 - T2
    - Time-to-validate = T4 - T3
    - Total time-to-recovery = T4 - T0
[ ] Llenar postmortem template en /var/log/streaming-bot-dr/dryrun-${INCIDENT_ID}/postmortem.md
[ ] Listar gaps detectados (orden critico -> trivial):
[ ] Notificar canal dry-run-ops con summary
[ ] Update calendario del proximo dry-run (T+90 dias)
```

## Plantilla de reporte trimestral

Llenar al cierre y guardar en `docs/runbooks/dr/dryrun-history/QYYYY-Q.md`
(no dentro de este modulo de runbooks; lo crea el operador en cada
ciclo).

```markdown
# Dry-run DR-2 trimestre QYYYY-Q

**Fecha**: YYYY-MM-DD
**Drill leader**: ________________________
**Observer**: ________________________
**Catalogo size**: N tracks, M distros activos
**% revenue al inicio del simulacro afectado por supuesto**: __%

## Metricas time-to-X

| Metric | T0/T1/.../T4 | Delta | Target |
|--------|--------------|-------|--------|
| Detect | T0 | n/a | n/a |
| Pause campaigns | T1 | T1-T0 | <30 min |
| Identify alt distro | T2 | T2-T1 | <30 min |
| Redistribute test track | T3 | T3-T2 | <60 min |
| Validate reassignment | T4 | T4-T3 | <30 min |
| **Total** | T4 | **T4-T0** | **<4h** |

## Gaps detectados

| Severidad | Gap | Owner del fix | Plazo |
|-----------|-----|---------------|-------|
| critical | (ej: tracks single-distro detectados) | operador | 30 dias |
| medium | (ej: workflow status API lento) | dev contractor | 60 dias |
| low | (ej: doc desactualizada) | operador | 90 dias |

## Recomendaciones para el siguiente trimestre

- ...
- ...

## Notas adicionales (postmortem completo si aplica)
...
```

## Reglas DURAS del simulacro

1. NUNCA pausar campaigns en produccion durante el dry-run.
2. NUNCA mandar emails simulados a distros reales (riesgo de
   confundir al provider).
3. NUNCA usar > 1 track expendable real por simulacro.
4. NUNCA omitir la phase 6 cleanup; un dry-run sin cleanup
   contamina staging.
5. NUNCA delegar el simulacro a un contractor sin presencia del
   operador principal: la decision sobre que track marcar como
   expendable es operador-only.
