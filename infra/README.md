# Infraestructura "Promocion de Catalogo Inteligente"

Infraestructura como codigo (Terraform + Docker Compose + Wireguard +
Cloudflare Tunnel) para levantar el plano de datos y observabilidad sobre
Hetzner bare-metal segun el plan Mes 1.

## Topologia

```
                 cloudflared (Tunnel)
                       |
                       v
        +-------------------------------+
        |   node-control (Hetzner EX)   |  Falkenstein DE
        |  - dashboard frontend         |
        |  - api FastAPI                |
        |  - temporal-frontend          |
        +---------------+---------------+
                        | wireguard mesh (10.10.0.0/24)
        +---------------+---------------+
        |                               |
        v                               v
+----------------+              +----------------+
| node-data      |              | node-workers   |
| Helsinki FI    |              | Ashburn US     |
|                |              |                |
| - postgres17   |              | - playwright/  |
| - clickhouse   |              |   patchright   |
| - redis        |              |   workers      |
| - temporal-srv |              | - browser pool |
| - minio (S3)   |              | - prometheus   |
| - grafana      |              |   exporter     |
| - loki         |              |                |
| - tempo        |              |                |
| - prometheus   |              |                |
| - alertmanager |              |                |
+----------------+              +----------------+
```

## Componentes

| Servicio       | Imagen oficial                    | Puerto interno |
|----------------|-----------------------------------|----------------|
| Postgres 17    | `postgres:17-alpine`              | 5432           |
| ClickHouse     | `clickhouse/clickhouse-server:24.10` | 9000 (TCP) / 8123 (HTTP) |
| Redis 7.4      | `redis:7.4-alpine`                | 6379           |
| Temporal       | `temporalio/auto-setup:1.25`      | 7233           |
| Temporal UI    | `temporalio/ui:2.31`              | 8080           |
| MinIO          | `minio/minio:RELEASE.2025-04-08T15-41-24Z` | 9000 / 9001 |
| Grafana        | `grafana/grafana:11.6.0`          | 3000           |
| Loki           | `grafana/loki:3.4.1`              | 3100           |
| Tempo          | `grafana/tempo:2.7.0`             | 3200           |
| Prometheus     | `prom/prometheus:v3.1.0`          | 9090           |
| Alertmanager   | `prom/alertmanager:v0.28.0`       | 9093           |
| Sentry         | `getsentry/self-hosted` (opcional)| 9000           |
| Cloudflared    | `cloudflare/cloudflared:2025.4.0` | -              |

## Prerrequisitos

- Cuenta Hetzner Cloud (HCLOUD_TOKEN) o robot dedicated.
- Cuenta Cloudflare con Zero Trust habilitado (CF_API_TOKEN).
- `terraform` >= 1.10 o `tofu` >= 1.9.
- `docker` + `docker compose` >= v2.27 en cada nodo.
- WireGuard kernel module (Linux >= 5.6 nativo).

## Quickstart (3 nodos)

```sh
# 1. Provisiona infra Hetzner
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars  # rellenar tokens
tofu init
tofu apply

# 2. Setea WireGuard mesh
cd ../wireguard
./gen-keys.sh                  # genera privadas/publicas para 3 nodos
./render-configs.sh            # genera wg0.conf por nodo
scp wg0-control.conf root@<control-ip>:/etc/wireguard/wg0.conf
scp wg0-data.conf    root@<data-ip>:/etc/wireguard/wg0.conf
scp wg0-workers.conf root@<workers-ip>:/etc/wireguard/wg0.conf
# en cada nodo: systemctl enable --now wg-quick@wg0

# 3. Levanta el plano de datos en node-data
ssh root@<data-ip>
cd /opt/streaming-bot/infra/compose
cp .env.example .env  # rellenar passwords
docker compose -f data-plane.yml --env-file .env up -d

# 4. Levanta el plano de control en node-control
ssh root@<control-ip>
cd /opt/streaming-bot/infra/compose
docker compose -f control-plane.yml --env-file .env up -d

# 5. Workers en node-workers
ssh root@<workers-ip>
cd /opt/streaming-bot/infra/compose
docker compose -f workers.yml --env-file .env up -d --scale worker=8

# 6. Cloudflare Tunnel (expone control plane sin abrir puertos)
ssh root@<control-ip>
cd /opt/streaming-bot/infra/cloudflare
cloudflared tunnel login
cloudflared tunnel create streaming-bot
cloudflared tunnel route dns streaming-bot dashboard.<tu-dominio>
docker compose -f cloudflared.yml up -d
```

## Servicios y endpoints internos (post-WireGuard mesh)

| Servicio       | Endpoint interno                |
|----------------|---------------------------------|
| Postgres       | `postgres://app:***@10.10.0.20:5432/streaming_bot` |
| ClickHouse HTTP| `http://10.10.0.20:8123`        |
| Redis          | `redis://10.10.0.20:6379`       |
| Temporal       | `10.10.0.20:7233`               |
| Temporal UI    | `http://10.10.0.20:8081`        |
| MinIO S3       | `http://10.10.0.20:9000`        |
| Grafana        | `http://10.10.0.20:3000`        |
| Prometheus     | `http://10.10.0.20:9090`        |

(El dashboard Next.js queda expuesto via Cloudflare Tunnel; los puertos
internos NUNCA se abren al internet.)

## Backups

- Postgres: `pg_dump` cron diario a MinIO bucket `backups/postgres/`.
- ClickHouse: `clickhouse-backup` semanal incremental a MinIO `backups/clickhouse/`.
- Snapshots Hetzner: weekly volume snapshot via Terraform.

Ver `infra/scripts/backup.sh` y `infra/scripts/restore.sh`.
