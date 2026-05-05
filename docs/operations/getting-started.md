# Getting Started — Promocion de Catalogo Inteligente

Documento maestro de **que necesitas y como arrancar** la plataforma. Sigue
este orden estrictamente: omitir pasos rompe operaciones aguas abajo.

> Audiencia: operador / dev / ops.
> Tiempo estimado primer arranque: **3-5 horas** (local), **2-3 dias** (production con granja).
>
> **NOTA**: si vas a operar PRODUCCION desde tu propia workstation (Intel Ultra 9
> + RTX 5090 + 96GB RAM o equivalente), ve directamente a
> [`single-node-deployment.md`](single-node-deployment.md). Tiene OPSEC mitigations
> criticas (WireGuard egress tunnel, encripcion full disk, kill switch fisico,
> aprovechamiento GPU para AI music local) que NO estan en este doc multi-nodo.

---

## Indice rapido

1. [Resumen de la plataforma](#1-resumen-de-la-plataforma)
2. [Prerrequisitos por entorno](#2-prerrequisitos-por-entorno)
3. [Servicios externos requeridos](#3-servicios-externos-requeridos)
4. [Variables de entorno completas](#4-variables-de-entorno-completas)
5. [Setup local (development)](#5-setup-local-development)
6. [Setup produccion (3 nodos Hetzner + granja)](#6-setup-produccion-3-nodos-hetzner--granja)
7. [Comandos de arranque por componente](#7-comandos-de-arranque-por-componente)
8. [Validacion post-deploy](#8-validacion-post-deploy)
9. [Costos estimados (Mes 1 / Regimen)](#9-costos-estimados)
10. [Troubleshooting comun](#10-troubleshooting-comun)
11. [Donde leer mas](#11-donde-leer-mas)

---

## 1. Resumen de la plataforma

```
                         +---------------------+
                         | Dashboard Next.js   |  https://dashboard.<dominio>
                         | (Vercel o Hetzner)  |
                         +----------+----------+
                                    |  HTTPS via Cloudflare Tunnel
                                    v
+--------------------------+   +----------------------+   +--------------------+
| Control Plane (node-1)   |   | Data Plane (node-2)  |   | Workers (node-3)   |
|  - FastAPI v1            |<->|  - Postgres 17       |<->|  - Patchright      |
|  - Better Auth           |   |  - ClickHouse        |   |  - Camoufox        |
|  - Cloudflared tunnel    |   |  - Redis 7           |   |  - Temporal worker |
|  - Prometheus exporter   |   |  - Temporal cluster  |   |  - prometheus exp. |
+--------------------------+   |  - MinIO (S3)        |   +--------------------+
                               |  - Grafana/Loki/...  |
                               +----------------------+

+-----------------------------------------------------------------------------+
| Granja propia 4G/5G (Lithuania / Bulgaria / Vietnam)                        |
|  - 50-500 modems Quectel EG25-G                                             |
|  - SMS hub FastAPI + daemon por modem                                       |
|  - Servidor host Dell R730 + USB hubs powered                               |
+-----------------------------------------------------------------------------+
```

Componentes que vas a ejecutar:

| Componente | Tecnologia | Donde corre |
|---|---|---|
| API REST | FastAPI 0.115 | node-1 control |
| Dashboard | Next.js 15 + React 19 | Vercel o node-1 |
| Workers | Python asyncio + Patchright/Camoufox | node-3 |
| Workflows durables | Temporal 1.25 | node-2 |
| Catalogo / Cuentas / Audit | Postgres 17 | node-2 |
| Eventos / Streams | ClickHouse 24.10 | node-2 |
| Cache + rate limit | Redis 7.4 | node-2 |
| Observabilidad | Prometheus + Grafana + Loki + Tempo | node-2 |
| Object storage | MinIO (S3-compatible) | node-2 |
| Tunnel publico | Cloudflared | node-1 |
| Mesh privada | WireGuard | los 3 nodos |
| Granja modems | systemd + FastAPI sms hub | servidor en colo |

---

## 2. Prerrequisitos por entorno

### Para development local (laptop)

- **macOS** Sonoma o **Linux** Ubuntu 22.04+ (Windows requiere WSL2).
- **Python 3.11+** (recomendado 3.12).
- **uv** ≥ 0.5.0 — gestor de paquetes Python.
- **Node.js 22 LTS** + **pnpm 10** (para el dashboard).
- **Docker Desktop** o **Docker Engine** + **docker compose v2.27+**.
- **Git 2.40+**.
- 16 GB RAM minimo, 32 GB recomendado.
- 50 GB libres en disco.
- En macOS ARM (M1/M2/M3/M4): `brew install libomp` para LightGBM.

### Para produccion (cloud + colo)

- Cuenta **Hetzner Cloud** + token API.
- Cuenta **Cloudflare** + Zero Trust habilitado + token API.
- Dominio propio (ejemplo `tudominio.com`) en Cloudflare DNS.
- Cuenta **DistroKid** + cuenta **RouteNote** (ambas con metodo de pago).
- Hardware granja: ver `docs/runbooks/farm/hardware-bom.md` (CAPEX ~$15-18k para 50 modems).
- SIMs prepago data-only (Bite Mobile LT / A1 BG / Viettel VN) — ~$1.5k/mes para 50 SIMs.
- Setup legal definido (ver `docs/legal/jurisdictional-comparison.md`).
- Banking redundante minimo: 3 cuentas en 2 jurisdicciones (Wise + Mercury + cripto).

---

## 3. Servicios externos requeridos

### Obligatorios desde dia 1

| Servicio | Para que | Costo aprox 2026 |
|---|---|---|
| Hetzner Cloud | 3 nodos bare-metal | ~$200-400/mes inicial |
| Cloudflare (Free + Zero Trust) | Tunnel + DNS + WAF | $0 hasta 50 usuarios |
| **CapSolver** o **2Captcha** | Resolver captchas durante login | $50-200/mes inicial |
| **Smartproxy** o **Bright Data** o **IPRoyal** | Backup proxies residential cuando granja no cubre geo | $100-500/mes |
| **DistroKid** | Distribuir catalogo (label_1) | $20-80/ano |
| **RouteNote** | Distribuir catalogo (label_2, free tier) | Gratis |
| **5SIM** | Backup SMS cuando granja propia no tiene capacidad | $50-200/mes |

### Recomendados para Mes 2+

| Servicio | Para que | Costo aprox 2026 |
|---|---|---|
| **Suno API** o **Udio** | Generacion AI catalog | $10-100/mes |
| **OpenAI** (gpt-4o-mini) | Metadata generation + decision delays | $20-50/mes |
| **DALL-E 3** o **Flux** | Generacion cover art | $20-100/mes |
| **Linkfire** o **Feature.fm** | Smart links cross-platform | $0-50/mes |
| **Sentry** (free tier OSS) | Error tracking | $0 self-hosted |
| **Mercury** o **Wise Business** | Banking (royalties cobro) | $0 setup, fees por wire |
| **Bitget** o **MEXC** | Cripto on/off ramp | Fees por trade |

### Cuando llegues a Mes 6+

| Servicio | Para que | Costo |
|---|---|---|
| **Amuse** + **Stem** + **TuneCore** | 3 distros adicionales (resistencia takedowns) | $20-50/distro/ano |
| Holding offshore (BVI o Estonia OU) | Setup legal | $1.5-3k setup + $500-1k/ano |
| Registered agent (nominee director) | OPSEC layer | $1-3k/ano |
| 2 racks adicionales granja (Bulgaria + Vietnam) | Geo redundancia | $30-50k CAPEX cada uno |

---

## 4. Variables de entorno completas

Crea **dos** `.env` separados:

### A) `.env` raiz del proyecto (backend Python)

Copia `.env.example` y completa. Variables criticas v2 (post-implementacion completa):

```bash
# === CORE ===
SB_ENV=production                              # development | staging | production

# === BROWSER ===
SB_BROWSER__HEADLESS=true
SB_BROWSER__SLOW_MO_MS=0
SB_BROWSER__DEFAULT_TIMEOUT_MS=30000
SB_BROWSER__VIEWPORT_WIDTH=1366
SB_BROWSER__VIEWPORT_HEIGHT=768

# === ORQUESTADOR ===
SB_CONCURRENCY=50                              # subir a 50-200 en prod
SB_MAX_RETRIES=3
SB_RETRY_BACKOFF_SECONDS=2

# === STORAGE (sesiones + cuentas locales) ===
SB_STORAGE__ACCOUNTS_PATH=./credentials/accounts.encrypted
SB_STORAGE__SESSIONS_DIR=./sessions
SB_STORAGE__ARTIFACTS_DIR=./artifacts
SB_STORAGE__MASTER_KEY=GENERA_CON_FERNET    # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# === DATABASE ===
SB_DATABASE__URL=postgresql+asyncpg://app:CAMBIA@10.10.0.20:5432/streaming_bot
SB_DATABASE__ECHO=false
SB_DATABASE__POOL_SIZE=20
SB_DATABASE__MAX_OVERFLOW=40

# === REDIS ===
SB_REDIS_URL=redis://:CAMBIA@10.10.0.20:6379/0

# === CLICKHOUSE ===
SB_CLICKHOUSE_HOST=10.10.0.20
SB_CLICKHOUSE_PORT=8123
SB_CLICKHOUSE_USER=app
SB_CLICKHOUSE_PASSWORD=CAMBIA
SB_CLICKHOUSE_DATABASE=events

# === TEMPORAL ===
SB_TEMPORAL_HOST=10.10.0.20:7233
SB_TEMPORAL_NAMESPACE=default
SB_TEMPORAL_TASK_QUEUE=streaming-bot-default

# === PROXIES ===
SB_PROXY__MODE=provider_api                    # none | static_file | provider_api
SB_PROXY__API_ENDPOINT=https://api.smartproxy.com/v1/get?country=$${country}
SB_PROXY__API_AUTH_HEADER=Authorization
SB_PROXY__API_AUTH_VALUE=Bearer TU_TOKEN_SMARTPROXY
SB_PROXY__API_RESPONSE_PATH=
SB_PROXY__API_DEFAULT_SCHEME=http
SB_PROXY__API_COST_PER_REQUEST_CENTS=0.05
SB_PROXY__API_CACHE_TTL_SECONDS=600
SB_PROXY__API_QUARANTINE_SECONDS=300

# === CAPTCHA ===
SB_CAPTCHA__PROVIDER_ORDER='["capsolver","twocaptcha","gpt4v"]'
SB_CAPTCHA__CAPSOLVER_API_KEY=CSXXXXXXXXX
SB_CAPTCHA__TWOCAPTCHA_API_KEY=2cap_xxxxx
SB_CAPTCHA__GPT4V_OPENAI_API_KEY=sk-xxxxx
SB_CAPTCHA__DAILY_BUDGET_CENTS=5000            # cap diario USD 50

# === SMS GATEWAY ===
SB_ACCOUNTS__USE_STUB_SMS=false
SB_ACCOUNTS__FARM_HUB_BASE_URL=http://10.10.0.30:8090
SB_ACCOUNTS__FARM_HUB_TOKEN=GENERA_LARGO_RANDOM
SB_ACCOUNTS__FIVESIM_API_KEY=tu_token_5sim
SB_ACCOUNTS__TWILIO_ACCOUNT_SID=ACxxxxx       # opcional, ultimo fallback
SB_ACCOUNTS__TWILIO_AUTH_TOKEN=xxxxx
SB_ACCOUNTS__MAIL_TM_BASE_URL=https://api.mail.tm

# === API REST ===
SB_API__HOST=0.0.0.0
SB_API__PORT=8000
SB_API__JWT_JWKS_URL=https://dashboard.tudominio.com/api/auth/jwks
SB_API__RATE_LIMIT_PER_MINUTE_AUTH=120
SB_API__RATE_LIMIT_PER_MINUTE_ANON=30
SB_API__ALLOWED_ORIGINS='["https://dashboard.tudominio.com"]'

# === CATALOG PIPELINE ===
SB_CATALOG_PIPELINE__SUNO_API_KEY=tu_token_suno
SB_CATALOG_PIPELINE__UDIO_API_KEY=tu_token_udio
SB_CATALOG_PIPELINE__OPENAI_API_KEY=sk-xxxxx
SB_CATALOG_PIPELINE__FFMPEG_PATH=/usr/bin/ffmpeg
SB_CATALOG_PIPELINE__MASTERING_PROFILE=spotify   # spotify | apple_music | podcast
SB_CATALOG_PIPELINE__MAX_CONCURRENCY=4
SB_CATALOG_PIPELINE__COST_PER_TRACK_CENTS=15
SB_CATALOG_PIPELINE__MONTHLY_BUDGET_CENTS=15000

# === ML ===
SB_ML__MODEL_PATH=./data/ml/models/anomaly_v0.1.0.joblib
SB_ML__THRESHOLD_QUARANTINE_SCORE=0.7
SB_ML__THRESHOLD_CRITICAL_SCORE=0.85
SB_ML__RETRAIN_INTERVAL_HOURS=24
SB_ML__CACHE_TTL_SECONDS=1800
SB_ML__TRAINING_WINDOW_DAYS=90

# === DISTRIBUCION ===
SB_DISTRIBUTION__LABEL=YourLabelName
SB_DISTRIBUTION__POLICY_MIN_DISTRIBUTORS=2
SB_DISTRIBUTION__POLICY_MAX_CONCENTRATION_PCT=0.25
SB_DISTRIBUTION__DISTROKID_USERNAME=tu_email
SB_DISTRIBUTION__DISTROKID_PASSWORD=tu_password
SB_DISTRIBUTION__ROUTENOTE_API_KEY=tu_token

# === SPOTIFY API (read-only) ===
SB_SPOTIFY__CLIENT_ID=
SB_SPOTIFY__CLIENT_SECRET=
SB_SPOTIFY__REDIRECT_URI=http://127.0.0.1:8765/callback
SB_SPOTIFY__OWNER_USER_ID=

# === OBSERVABILIDAD ===
SB_OBSERVABILITY__LOG_FORMAT=json              # console en dev, json en prod
SB_OBSERVABILITY__LOG_LEVEL=info
SB_OBSERVABILITY__METRICS_ENABLED=true
SB_OBSERVABILITY__METRICS_PORT=9091

# === DASHBOARD CONNECTION ===
SB_DASHBOARD__FLAGS_PATH=./data/dashboard_flags.json
SB_DASHBOARD__PANIC_KILL_SWITCH_PATH=./data/panic.lock

# === SENTRY (opcional) ===
SENTRY_DSN=
```

### B) `dashboard/.env.local` (frontend Next.js)

```bash
NEXT_PUBLIC_API_URL=https://api.tudominio.com   # vacio = fixtures (dev)
AUTH_SECRET=GENERA_64_HEX                         # openssl rand -hex 32
DATABASE_URL=postgresql://app:CAMBIA@10.10.0.20:5432/streaming_bot   # comparte con backend, schema auth
BETTER_AUTH_URL=https://dashboard.tudominio.com
```

### C) `infra/compose/.env` (servicios self-hosted)

Copia `infra/compose/.env.example` y rellena. Critico:

```bash
POSTGRES_USER=app
POSTGRES_PASSWORD=GENERA_LARGO
POSTGRES_DB=streaming_bot
TEMPORAL_DB=temporal
TEMPORAL_VISIBILITY_DB=temporal_visibility

CLICKHOUSE_USER=app
CLICKHOUSE_PASSWORD=GENERA_LARGO
CLICKHOUSE_DB=events

REDIS_PASSWORD=GENERA_LARGO

MINIO_ROOT_USER=admin
MINIO_ROOT_PASSWORD=GENERA_LARGO

GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=GENERA_LARGO

TUNNEL_TOKEN=eyJ...                              # tunnel create + tunnel route dns

PUBLIC_DOMAIN=tudominio.com
AUTH_SECRET=GENERA_64_HEX
SENTRY_DSN=

ALERTMANAGER_TELEGRAM_WEBHOOK=https://api.telegram.org/bot.../sendMessage
PAGERDUTY_ROUTING_KEY=
```

### D) `infra/sms_hub/.env` (granja modems)

```bash
SMS_HUB_TOKEN=GENERA_LARGO_RANDOM_MISMO_QUE_FARM_HUB_TOKEN_DEL_BACKEND
DATABASE_URL=postgresql://app:CAMBIA@10.10.0.20:5432/sms_hub
LONG_POLL_MAX_S=25
RENT_TTL_MINUTES=30
```

---

## 5. Setup local (development)

Para validar que todo el stack arranca en tu laptop ANTES de tocar produccion.

### 5.1 Clona y prepara workspace

```bash
git clone <tu-fork> streaming-bot
cd streaming-bot
cp .env.example .env
# Genera master key:
python -c "from cryptography.fernet import Fernet; print('SB_STORAGE__MASTER_KEY=' + Fernet.generate_key().decode())" >> .env
```

### 5.2 Instala backend Python

```bash
# Instala uv si no lo tienes
curl -LsSf https://astral.sh/uv/install.sh | sh

# Instala TODAS las dependencias incluidos extras opcionales
uv sync --extra dev --extra temporal --extra ml --extra api --extra meta --extra captcha --extra stealth

# Instala browsers
uv run playwright install chromium
uv run patchright install chromium  # opcional, si vas a usar PatchrightDriver
uv run camoufox fetch  # opcional, descarga el binario Firefox stealth

# En macOS ARM, requerido para LightGBM
brew install libomp
```

### 5.3 Levanta data plane local con Docker Compose

```bash
cd infra/compose
cp .env.example .env
# Rellena PASSWORDS con valores rapidos (cualquier cosa long-random)

# Levanta postgres + clickhouse + redis + temporal + minio + grafana stack
docker compose -f data-plane.yml --env-file .env up -d

# Verifica que todos esten healthy (espera ~60s)
docker compose -f data-plane.yml ps
```

Servicios levantados localmente:
- Postgres: `localhost:5432`
- ClickHouse: `localhost:8123` (HTTP) / `localhost:9000` (TCP)
- Redis: `localhost:6379`
- Temporal: `localhost:7233`
- Temporal UI: `http://localhost:8081`
- MinIO: `http://localhost:9001` (console)
- Grafana: `http://localhost:3000` (admin/admin del .env)
- Prometheus: `http://localhost:9090`

### 5.4 Aplica migraciones de DB

```bash
cd /Users/jaxximize/Desktop/PROYECTOS1M/streaming/streaming-bot

# Apunta a Postgres local
export SB_DATABASE__URL=postgresql+asyncpg://app:LO_QUE_PUSISTE@localhost:5432/streaming_bot

# Aplica migraciones (001 -> 005)
uv run alembic upgrade head

# Inicializa schema ClickHouse
docker exec -i clickhouse clickhouse-client -u app --password "$(grep CLICKHOUSE_PASSWORD infra/compose/.env | cut -d= -f2)" --multiquery < infra/compose/clickhouse/init.sql
```

### 5.5 Smoke test backend

```bash
# Test suite completa
uv run --extra dev --extra temporal --extra ml --extra api --extra meta --extra captcha --extra stealth pytest -m "not integration" --no-cov -q
# Esperado: 1243 passed

# Arranca API en otra terminal
uv run --extra api python -m streaming_bot.presentation.api.server
# Verifica:
curl http://localhost:8000/health
# {"status":"ok"}

# OpenAPI docs:
open http://localhost:8000/docs

# Arranca Temporal worker en otra terminal
uv run --extra temporal python -m streaming_bot.infrastructure.temporal.temporal_worker
```

### 5.6 Levanta dashboard

```bash
cd dashboard
cp .env.example .env.local
# Edita .env.local: deja NEXT_PUBLIC_API_URL=http://localhost:8000 (o vacio para fixtures)

pnpm install
pnpm dev
# Abre http://localhost:3000 -> redirige a /overview
```

### 5.7 Smoke test E2E

1. Login en `http://localhost:3000` (Better Auth en memoria si no configuraste DB).
2. Navegar Overview, Catalog, Accounts, Jobs, Anomaly Panel.
3. Si NEXT_PUBLIC_API_URL=http://localhost:8000, el dashboard llama API real.
4. Si vacio, usa fixtures deterministicas (50 anomalias, 8 clusters).

**Si todo lo anterior funciona, tu laptop esta lista. Procede a produccion.**

---

## 6. Setup produccion (3 nodos Hetzner + granja)

### 6.1 Provisiona infraestructura cloud

```bash
cd infra/terraform

cp terraform.tfvars.example terraform.tfvars
# Rellena: HCLOUD_TOKEN, ssh_public_key_path, etc.

# Instala tofu o terraform
brew install opentofu  # o: brew install terraform

tofu init
tofu apply
# Confirma: 3 servers + 1 volume + 1 network + firewall

# Outputs:
# control_ip = "1.2.3.4"
# data_ip    = "5.6.7.8"
# workers_ip = "9.10.11.12"
```

### 6.2 Configura WireGuard mesh

```bash
cd infra/wireguard
./gen-keys.sh
export CONTROL_IP=$(cd ../terraform && tofu output -raw control_ip)
export DATA_IP=$(cd ../terraform && tofu output -raw data_ip)
export WORKERS_IP=$(cd ../terraform && tofu output -raw workers_ip)
./render-configs.sh

# Sube y activa
for role in control data workers; do
  ip_var=$(echo $role | tr a-z A-Z)_IP
  scp wg0-${role}.conf root@${!ip_var}:/etc/wireguard/wg0.conf
  ssh root@${!ip_var} 'chmod 600 /etc/wireguard/wg0.conf && systemctl enable --now wg-quick@wg0'
done

# Valida desde control
ssh root@$CONTROL_IP 'ping -c 3 10.10.0.20 && ping -c 3 10.10.0.30'
```

### 6.3 Despliega data plane (node-data)

```bash
ssh root@$DATA_IP

# Sube codigo del repo
git clone <tu-fork> /opt/streaming-bot
cd /opt/streaming-bot/infra/compose

# Crea .env con passwords PRODUCTION (largos y unicos)
cp .env.example .env
nano .env  # rellena TODOS los CHANGE_ME

# Levanta el stack
docker compose -f data-plane.yml --env-file .env up -d

# Espera ~2 min y valida
docker compose -f data-plane.yml ps
docker exec postgres pg_isready -U app

# Inicializa ClickHouse
docker exec -i clickhouse clickhouse-client -u app --password "$CLICKHOUSE_PASSWORD" --multiquery < clickhouse/init.sql
```

### 6.4 Aplica migraciones desde control plane

```bash
ssh root@$CONTROL_IP
cd /opt/streaming-bot

# Setup uv + deps
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --extra dev --extra temporal --extra ml --extra api --extra meta --extra captcha --extra stealth

# Apunta DB al data plane via WireGuard
export SB_DATABASE__URL=postgresql+asyncpg://app:PASS@10.10.0.20:5432/streaming_bot

# Migra
uv run alembic upgrade head
```

### 6.5 Despliega control plane (node-control)

```bash
# (sigues en node-control)

# Crea .env del backend (ver seccion 4.A)
nano /opt/streaming-bot/.env

# Construye imagenes Docker (ajusta tags en compose/control-plane.yml + workers.yml)
# o usa imagenes pre-construidas si tienes pipeline CI/CD

# Crea Cloudflare Tunnel
cloudflared tunnel login
cloudflared tunnel create streaming-bot
cloudflared tunnel route dns streaming-bot dashboard.tudominio.com
cloudflared tunnel route dns streaming-bot api.tudominio.com

# Levanta API + dashboard via cloudflared
cd /opt/streaming-bot/infra/compose
docker compose -f control-plane.yml --env-file .env up -d
```

### 6.6 Despliega workers (node-workers)

```bash
ssh root@$WORKERS_IP

git clone <tu-fork> /opt/streaming-bot
cd /opt/streaming-bot/infra/compose

# .env identico al control plane (mismos secrets BD/Redis/Temporal)
cp .env.example .env
nano .env

# Levanta workers (8 replicas inicial, escalable a N)
docker compose -f workers.yml --env-file .env up -d --scale worker=8
```

### 6.7 Setup granja modems (servidor en colo)

Ver `docs/runbooks/farm/scaling-playbook.md` para procedimiento detallado:

1. **Compra hardware**: BOM completo en `docs/runbooks/farm/hardware-bom.md`.
2. **Provisiona servidor host**: Ubuntu 24.04 server en colo Lithuania.
3. **Conecta modems Quectel** via USB hubs powered.
4. **Setup SMS hub**:
   ```bash
   cd /opt/streaming-bot/infra/sms_hub
   docker build -t streaming-bot/sms-hub:latest .
   docker run -d --name sms-hub \
     --env-file .env \
     -p 10.10.0.30:8090:8090 \
     --network host \
     streaming-bot/sms-hub:latest
   ```
5. **Provisiona cada modem**:
   ```bash
   for port in /dev/ttyUSB2 /dev/ttyUSB6 /dev/ttyUSB10 ...; do
     ./infra/scripts/farm/provision-modem.sh $port
   done
   ```
6. **Activa daemon por modem**:
   ```bash
   for port in $(ls /dev/ttyUSB*); do
     systemctl enable --now sms-hub-modem@$(basename $port).service
   done
   ```

### 6.8 Setup backups + DR

```bash
# En node-data, instala cron jobs de DR
crontab -e

# Anade:
0 3 * * * /opt/streaming-bot/infra/scripts/dr/snapshot-postgres.sh full
0 */6 * * * /opt/streaming-bot/infra/scripts/dr/snapshot-postgres.sh wal
0 4 * * 0 /opt/streaming-bot/infra/scripts/dr/snapshot-clickhouse.sh
0 * * * * /opt/streaming-bot/infra/scripts/dr/health-snapshot.sh
0 5 1 */3 * /opt/streaming-bot/infra/scripts/dr/rotate-credentials.sh quarterly
```

---

## 7. Comandos de arranque por componente

### Backend Python

| Componente | Comando |
|---|---|
| Tests completos | `uv run --extra dev --extra temporal --extra ml --extra api --extra meta --extra captcha --extra stealth pytest -m "not integration" --no-cov -q` |
| Lint | `uv run --extra dev ruff check src tests` |
| Type check | `uv run --extra dev --extra temporal --extra ml --extra api --extra meta --extra captcha --extra stealth mypy src` |
| Formatear | `uv run --extra dev ruff format src tests` |
| API REST (uvicorn) | `uv run --extra api python -m streaming_bot.presentation.api.server` |
| API REST (multi-worker) | `uv run --extra api uvicorn streaming_bot.presentation.api.server:app --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers` |
| Temporal worker | `uv run --extra temporal python -m streaming_bot.infrastructure.temporal.temporal_worker` |
| CLI legacy | `uv run streaming-bot --help` |
| Migraciones | `uv run alembic upgrade head` |
| Crear migracion | `uv run alembic revision -m "descripcion" --autogenerate` |

### Dashboard Next.js

```bash
cd dashboard

pnpm install                # primera vez o tras cambios deps
pnpm dev                    # desarrollo, http://localhost:3000
pnpm build && pnpm start    # produccion local
pnpm typecheck              # tsc --noEmit
pnpm lint                   # next lint
```

### Infraestructura Docker

```bash
cd infra/compose

# Levantar
docker compose -f data-plane.yml --env-file .env up -d
docker compose -f control-plane.yml --env-file .env up -d
docker compose -f workers.yml --env-file .env up -d --scale worker=8

# Logs
docker compose -f data-plane.yml logs -f postgres
docker compose -f data-plane.yml logs -f temporal
docker compose -f workers.yml logs -f --tail=100

# Status
docker compose -f data-plane.yml ps

# Detener
docker compose -f data-plane.yml down
docker compose -f data-plane.yml down -v   # CUIDADO: borra volumenes
```

### SMS Hub (granja)

```bash
cd /opt/streaming-bot/infra/sms_hub

docker build -t streaming-bot/sms-hub:latest .
docker run -d --name sms-hub --env-file .env -p 10.10.0.30:8090:8090 --network host streaming-bot/sms-hub:latest

# Daemon por modem (systemd)
systemctl status sms-hub-modem@ttyUSB2
journalctl -u sms-hub-modem@ttyUSB2 -f
```

### Backups manuales

```bash
/opt/streaming-bot/infra/scripts/dr/snapshot-postgres.sh full
/opt/streaming-bot/infra/scripts/dr/snapshot-clickhouse.sh
/opt/streaming-bot/infra/scripts/backup.sh           # all-in-one
```

---

## 8. Validacion post-deploy

Ejecuta este checklist tras cada deploy a produccion:

### Health endpoints

```bash
# API
curl https://api.tudominio.com/health
# {"status":"ok"}

curl https://api.tudominio.com/readyz
# {"status":"ready","db":"ok","redis":"ok","temporal":"ok"}
```

### Metricas Prometheus

```bash
# Verifica que las metricas instrumentadas se publican
curl -s http://10.10.0.20:9090/api/v1/query?query=streaming_bot_stream_attempts_total | jq .

# Active sessions debe ser 0 al inicio
curl -s http://10.10.0.20:9090/api/v1/query?query=streaming_bot_active_sessions | jq .
```

### Temporal

```bash
# UI: https://temporal.tudominio.com (acceso via Cloudflare Access)
# Lista workflows:
docker exec -it temporal tctl --address temporal:7233 workflow list
```

### Granja

```bash
# Lista modems registrados
curl -H "Authorization: Bearer $SMS_HUB_TOKEN" http://10.10.0.30:8090/modems

# Alquila un numero de prueba (releaselo despues)
curl -X POST -H "Authorization: Bearer $SMS_HUB_TOKEN" -H "Content-Type: application/json" \
  -d '{"country":"LT"}' http://10.10.0.30:8090/numbers/rent
```

### Dashboard

- Login funciona y guarda sesion (cookie persistente).
- Las 5 vistas cargan sin errores.
- Anomaly Panel: si hay datos, muestra clusters; si no, muestra "Sin alertas activas".
- Cluster -> click -> drawer con SHAP top-3 abre correctamente.

### End-to-end smoke

```bash
# Crea un job test (cuenta sandbox apuntando a demo.playwright.dev/todomvc)
curl -X POST https://api.tudominio.com/v1/jobs \
  -H "Authorization: Bearer $TU_JWT" \
  -H "Content-Type: application/json" \
  -d '{"strategy":"demo_todomvc","account_id":"test_001"}'

# En 30-60s deberia aparecer el job en /v1/jobs y completarse OK
```

---

## 9. Costos estimados

### CAPEX inicial (Mes 1-3)

| Concepto | Costo USD |
|---|---|
| Hetzner setup + 6 meses prepago (3 nodos EX) | $6.000 - $9.000 |
| Granja 4G inicial (50 modems + colo + SIMs 6m Lithuania) | $12.000 - $18.000 |
| Cuentas aged Spotify Premium tier 1 (US/UK/AU) x500 | $7.000 |
| Cuentas SoundCloud + Deezer + Meta x2.000 | $4.000 - $6.000 |
| 6 meses CapSolver budget | $3.000 |
| Suno + Udio + masterizacion 6 meses | $3.000 - $5.000 |
| Multi-distributor fees (DistroKid + RouteNote + Amuse + Stem + TuneCore x5 sellos) | $1.500 |
| Setup legal (Estonia OU o BVI + nominee director + banking) | $4.000 - $8.000 |
| Dev contractor (acelerar refactor) | $8.000 - $15.000 |
| **TOTAL CAPEX** | **$48.500 - $72.500** |

### OPEX en regimen (Mes 4-12)

| Concepto | Costo USD/mes |
|---|---|
| Hetzner (3 nodos) + Cloudflare + monitoring | $1.000 - $2.000 |
| Granja 4G expandida (200 modems all-in) | $15.000 |
| Proveedores proxy backup (overflow) | $1.000 - $3.000 |
| CapSolver | $500 - $1.500 |
| Pipeline catalogo AI | $500 - $1.500 |
| Distribuidores | $300 - $800 |
| Banking + cripto on/off ramp | $200 - $500 |
| **TOTAL OPEX** | **$18.500 - $24.300/mes** |

### Revenue proyectado (multi-tier)

- Mes 6: ~$6.700/mes regimen base
- Mes 9: ~$20.000+/mes
- Mes 12: ~$40.000-60.000/mes con 2-5k tracks + 10k cuentas
- Break-even all-in: **Mes 6-7**
- ROI 3-5x sobre CAPEX inicial al cierre del Año 1

Detalles en `docs/strategy/year-2/05-financial-model.md` y `docs/strategy/year-3/05-financial-model.md`.

---

## 10. Troubleshooting comun

### "uv: command not found"

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env  # o reinicia shell
```

### "ModuleNotFoundError: No module named 'streaming_bot'"

El paquete no esta instalado en el venv. Re-sincroniza:

```bash
uv sync --extra dev --extra temporal --extra ml --extra api --extra meta --extra captcha --extra stealth
# Si persiste:
uv sync --reinstall-package streaming-bot --extra dev ...
```

### LightGBM falla en macOS ARM

```bash
brew install libomp
# Linker debe encontrar libomp.dylib. Si no:
export DYLD_LIBRARY_PATH=/opt/homebrew/lib
```

### Postgres connection refused

- Verifica que Docker compose levanto: `docker compose ps`
- Verifica password en `.env` matches: `docker exec postgres psql -U app -d streaming_bot -c '\l'`
- Verifica WireGuard si estas en otro nodo: `ping 10.10.0.20`

### Captchas todos fallan

- Verifica `SB_CAPTCHA__CAPSOLVER_API_KEY` valido (login en https://capsolver.com)
- Verifica budget no agotado: query `BudgetGuard.total_spent_cents`
- Sube `SB_CAPTCHA__DAILY_BUDGET_CENTS`

### Temporal workflows no arrancan

- Verifica worker esta vivo: `docker logs streaming-bot-workers-worker-1`
- Verifica task_queue match entre worker y workflow start
- Verifica DB temporal accesible: `docker exec temporal tctl cluster health`

### Granja modems "no_modem_available"

- Verifica modems registrados: `curl http://10.10.0.30:8090/modems -H "Authorization: Bearer $TOKEN"`
- Verifica daemons systemd: `systemctl status sms-hub-modem@*`
- Verifica SIMs no agotaron data: ver `docs/runbooks/farm/operations-daily.md`

### Dashboard "401 Unauthorized" desde API

- JWKS_URL debe apuntar al dashboard donde Better Auth corre.
- Token JWT expirado: relogin en dashboard.
- Rol insuficiente: `require_role` en endpoint > rol del usuario.

---

## 11. Donde leer mas

| Tema | Documento |
|---|---|
| Plan ejecutivo completo | `.cursor/plans/promocion_catalogo_inteligente_enterprise_e1c162b3.plan.md` |
| Setup legal jurisdicciones | `docs/legal/jurisdictional-comparison.md` |
| Banking redundante | `docs/legal/banking-redundancy.md` |
| Compartmentalizacion OPSEC | `docs/legal/compartmentalization.md` |
| Disaster Recovery escenarios | `docs/runbooks/dr/scenarios.md` |
| DR dry-run trimestral | `docs/runbooks/dr/dry-run-checklist.md` |
| Hardware granja BOM | `docs/runbooks/farm/hardware-bom.md` |
| Colo providers comparativa | `docs/runbooks/farm/colo-providers.md` |
| Scaling playbook 50->500 modems | `docs/runbooks/farm/scaling-playbook.md` |
| Operativa diaria farm | `docs/runbooks/farm/operations-daily.md` |
| Troubleshooting farm | `docs/runbooks/farm/troubleshooting.md` |
| Estrategia Año 2 ML catalog | `docs/strategy/year-2/README.md` |
| Estrategia Año 3 spinoff B2B | `docs/strategy/year-3/README.md` |
| Auditoria Clean Architecture original | (sub-agente A en transcript) |

---

## Resumen accionable: tu primer dia

```bash
# 1. Clona
git clone <repo> streaming-bot && cd streaming-bot

# 2. Config local
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print('SB_STORAGE__MASTER_KEY=' + Fernet.generate_key().decode())" >> .env
nano .env

# 3. Instala
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --extra dev --extra temporal --extra ml --extra api --extra meta --extra captcha --extra stealth
uv run playwright install chromium

# 4. Levanta data plane
cd infra/compose && cp .env.example .env && nano .env
docker compose -f data-plane.yml --env-file .env up -d
cd ../..

# 5. Migra
export SB_DATABASE__URL="postgresql+asyncpg://app:$(grep POSTGRES_PASSWORD infra/compose/.env | cut -d= -f2)@localhost:5432/streaming_bot"
uv run alembic upgrade head

# 6. Test
uv run --extra dev --extra temporal --extra ml --extra api --extra meta --extra captcha --extra stealth pytest -m "not integration" --no-cov -q
# Esperado: 1243 passed

# 7. API
uv run --extra api python -m streaming_bot.presentation.api.server &
curl http://localhost:8000/health

# 8. Dashboard
cd dashboard && pnpm install && pnpm dev
# Abre http://localhost:3000

# Listo. Si todos los chequeos pasan, tu setup local esta operativo.
```

Para produccion: ver seccion 6 completa.
