# Disaster Recovery — indice operativo

Este modulo cubre los 6 escenarios de fallo previstos en el plan
ejecutivo y los procedimientos exactos para recuperar operacion sin
perder mas del 30% del revenue mensual en el peor escenario.

## RTO / RPO targets globales

| Componente | RTO (Recovery Time Objective) | RPO (Recovery Point Objective) | Justificacion |
|------------|-------------------------------|---------------------------------|---------------|
| **Global (operacion completa)** | **4 horas** | n/a | Revenue impact aceptable: <30% mensual perdida si falla en un dia |
| Postgres (state, catalogo, accounts, audit) | 1h | **15 min** (PITR via WAL) | Datos transaccionales, perdida de 15 min = perdida de a lo sumo 1 batch de jobs y warming step |
| ClickHouse (events, metricas) | 4h | **1h** | Analitico, perdida de 1h = no afecta operacion (solo dashboard analytics) |
| Redis (cache, rate limits) | 30 min | n/a (volatil aceptable) | Reconstruible desde Postgres + reset de rate limits es ok |
| MinIO (audio masters, sesiones) | 2h | 24h (lifecycle replicas) | Sesiones snapshots regenerables; masters multi-distros, recuperables via re-download |
| Temporal (workflows + history) | 1h | 15 min (sigue Postgres) | Temporal usa Postgres como persistence, sigue su PITR |
| Granja modems (control plane SMS hub) | 2h | n/a | Servicio statefull pero idempotente; restart ok |
| Banking | 24-48h (vease `legal/banking-redundancy.md`) | n/a | Backup tier 1 + 2 + cripto OTC |

## Mapa de documentos DR

| Documento | Cuando se usa |
|-----------|---------------|
| [`scenarios.md`](./scenarios.md) | Durante un incidente. Contiene los 6 procedimientos paso a paso (DR-1 ... DR-6). |
| [`dry-run-checklist.md`](./dry-run-checklist.md) | Cada trimestre (calendario fijo). Simulacion controlada de DR-2 (takedown masivo). |
| [`postmortem-template.md`](./postmortem-template.md) | T+24h despues de cualquier incidente real. |

## Mapa de scripts DR (shell)

| Script | Frecuencia | Trigger |
|--------|-----------|---------|
| [`infra/scripts/dr/snapshot-postgres.sh`](../../../infra/scripts/dr/snapshot-postgres.sh) | Diario `0 2 * * *` + on-demand | Cron daily, manual antes de upgrade |
| [`infra/scripts/dr/restore-postgres.sh`](../../../infra/scripts/dr/restore-postgres.sh) | On-demand | DR-1, DR-6 |
| [`infra/scripts/dr/snapshot-clickhouse.sh`](../../../infra/scripts/dr/snapshot-clickhouse.sh) | Diario `0 3 * * *` (full Sunday, incremental rest) | Cron daily |
| [`infra/scripts/dr/restore-clickhouse.sh`](../../../infra/scripts/dr/restore-clickhouse.sh) | On-demand | DR-1 |
| [`infra/scripts/dr/rotate-credentials.sh`](../../../infra/scripts/dr/rotate-credentials.sh) | Trimestral + on-demand | DR-6, audit trim-7 |
| [`infra/scripts/dr/health-snapshot.sh`](../../../infra/scripts/dr/health-snapshot.sh) | Horario `0 * * * *` | Cron hourly, manual antes de upgrade |

## Localizacion de backups

| Backup | Almacenamiento primario | Replica geografica |
|--------|--------------------------|---------------------|
| Postgres dumps + WAL | `node-data` MinIO bucket `dr/postgres/` (Helsinki FI) | Backblaze B2 bucket `streaming-bot-dr-postgres` (US-West) |
| ClickHouse snapshots | `node-data` MinIO bucket `dr/clickhouse/` (Helsinki FI) | Backblaze B2 bucket `streaming-bot-dr-clickhouse` (US-West) |
| Health snapshots horarios | `node-data` MinIO bucket `dr/health/` (Helsinki FI) | n/a (rolling 30 dias) |
| Credentials archive (Vault encrypted) | `node-control` MinIO bucket `dr/secrets/` (Falkenstein DE) | Local encrypted USB en safe deposit box |
| Grafana dashboards JSON | `node-data` MinIO bucket `dr/grafana/` (Helsinki FI) | Git private repo (encrypted) |

## Roles y responsabilidades durante un incidente

| Rol | Responsable primario | Backup |
|-----|----------------------|--------|
| **Incident Commander** | Operador principal | Tax lawyer en jurisdiccion principal (solo si IC esta indisponible) |
| **Comms (Telegram + email a contractors)** | Operador principal | n/a |
| **Tech recovery (scripts, DBs)** | Operador principal o contractor dev de turno | n/a |
| **Legal coordination** | Tax lawyer + nominee director | Backup tax lawyer en jurisdiccion secundaria |

> Para operacion solo-operador, todos los roles colapsan en uno. La
> consecuencia es que TODA accion DR debe estar scriptada y
> ejecutable con un solo comando para que el operador no improvise
> bajo estres.

## Convenciones

- TODA accion ejecutada durante un DR debe loguear a
  `/var/log/streaming-bot-dr/{incident_id}/timeline.log` con
  timestamp ISO-8601 UTC.
- TODA decision tomada durante un DR debe ir como entry timestamped
  al postmortem en construccion.
- NUNCA modificar el codigo en main durante un DR; siempre rama
  `hotfix/dr-{incident_id}` aunque el "fix" sea trivial.

## Comunicacion durante incidente

Canal primario: Telegram bot privado en grupo dedicado `dr-ops`
(via Alertmanager webhook).

Canal secundario: PGP-encrypted email a `legal@<entity-domain>`
para coordinacion con tax lawyer si aplica.

Channel **nunca usado** durante incidente: cualquier red social,
email personal, mensajeria comun (WhatsApp, Telegram personal,
Discord publico).
