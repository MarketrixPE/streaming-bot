# Single-Node Deployment — Workstation Propia

Documento operativo para correr **toda la plataforma en una sola maquina fisica**
(workstation enterprise-grade). Reemplaza el setup multi-nodo Hetzner del
`getting-started.md` cuando la decision es no usar cloud.

> **AVISO CRITICO OPSEC**: este modo concentra todo el riesgo legal/operativo en
> un solo punto fisico bajo tu identidad. Lee la seccion [Riesgos asumidos](#riesgos-asumidos)
> antes de continuar. Las mitigaciones de la seccion [Stack OPSEC obligatorio](#stack-opsec-obligatorio-no-skipear)
> NO son opcionales si vas a operar en modo agresivo.

---

## Indice

1. [Hardware target](#1-hardware-target-workstation)
2. [Topologia single-node](#2-topologia-single-node)
3. [Riesgos asumidos](#3-riesgos-asumidos)
4. [Stack OPSEC obligatorio (no skipear)](#4-stack-opsec-obligatorio-no-skipear)
5. [Setup paso a paso](#5-setup-paso-a-paso)
6. [Aprovechamiento GPU RTX 5090](#6-aprovechamiento-gpu-rtx-5090)
7. [Resource limits y tuning](#7-resource-limits-y-tuning)
8. [Backups offsite obligatorios](#8-backups-offsite-obligatorios)
9. [Kill switch fisico](#9-kill-switch-fisico)
10. [Checklist post-deploy](#10-checklist-post-deploy)
11. [Cuando deberias migrar a multi-nodo](#11-cuando-deberias-migrar-a-multi-nodo)

---

## 1. Hardware target (workstation)

Tu workstation actual es **ideal** para single-node production:

| Componente | Tu spec | Headroom para platform |
|---|---|---|
| CPU | Intel Core Ultra 9 285K (24c/24t, hibrido P-cores + E-cores) | 60-80 workers concurrent + Postgres + ClickHouse + Temporal + dashboard |
| RAM | 64GB + 32GB = **96GB DDR5 6000MHz** | Postgres 16GB + ClickHouse 24GB + Redis 4GB + workers 32GB + sistema 8GB + buffer 12GB |
| Storage | 4x 1TB NVMe Kingston NV3 (4TB total) | DB 1TB + ClickHouse 1.5TB + sessions/artifacts 800GB + sistema 700GB |
| GPU | RTX 5090 32GB GDDR7 | Generacion AI music local + LLM inference behavioral ML + LightGBM GPU accel |
| PSU | Xigmatek Titan PT 1200W Platinum | Margen amplio incluso con GPU bajo carga |
| Cooling | LC-360 AIO + Gamemax Infinity Pro 5 fans | Sostenible 24/7 si AC del room < 28C |

**Lo que TIENES que sumar al BOM** (CRITICO operacion 24/7):

| Item | Costo aprox | Por que |
|---|---|---|
| **APC SmartUPS 1500VA** o **Schneider SMT1500RM2UC** | S/. 2.000 - 2.800 | Sin UPS, un corte de luz = perder cuentas (sessions corruptas, BD recovery, downtime) |
| **Modem 4G/5G failover** + plan datos backup ISP | S/. 600 hardware + S/. 80/mes | Tu ISP residencial NO es 99.9% uptime. Failover automatico via OpenWRT/pfSense |
| **NAS o disco USB 8TB** para backups locales | S/. 1.500 | RAID 1 de la workstation NO sustituye backups externos (ransomware, fallo controladora) |
| **Cloud storage offsite** (Backblaze B2 / Wasabi) | $5-15/mes | Si tu casa se inunda/incendia, tienes 30 dias para recuperar desde offsite |
| **VPS offshore micro** ($5/mes Hetzner CCX13 o Vultr) | S/. 18/mes | Egress tunnel WireGuard. Tu IP residencial peruana NUNCA debe tocar Spotify/banking directamente |

**Costo total adicional**: ~S/. 4.700 setup + S/. 100/mes recurrente. **No negociable** si la operacion es seria.

---

## 2. Topologia single-node

```
                    +------------------------+
                    | Internet ISP residencial|
                    +-----------+------------+
                                |
                    +-----------v------------+
                    | Router + Firewall      |
                    | OpenWRT/pfSense        |
                    | Failover ISP1 -> 4G    |
                    +-----------+------------+
                                |
                    +-----------v------------+
                    | UPS APC 1500VA         |
                    | (15-25 min autonomia)  |
                    +-----------+------------+
                                |
+-------------------------------v-------------------------------+
| WORKSTATION (tu PC)                                           |
| Intel Ultra 9 285K + 96GB DDR5 + 4TB NVMe + RTX 5090         |
|                                                               |
| +-------------------------------------------------------+    |
| | Capa OPSEC (host network)                             |    |
| | - WireGuard tunnel a VPS offshore (todo egress sale   |    |
| |   por ahi: DSPs, banking, distribuidor)               |    |
| | - Firewall iptables: workstation NO acepta inbound    |    |
| |   directo, solo via Cloudflare Tunnel                 |    |
| +-------------------------------------------------------+    |
|                                                               |
| +-------------------------------------------------------+    |
| | Docker Compose: data + control + workers en 1 host    |    |
| |                                                       |    |
| | +-------------+ +-------------+ +------------------+ |    |
| | | Postgres 17 | | ClickHouse  | | Redis 7          | |    |
| | | 16GB RAM    | | 24GB RAM    | | 4GB RAM          | |    |
| | +-------------+ +-------------+ +------------------+ |    |
| |                                                       |    |
| | +-------------+ +-------------+ +------------------+ |    |
| | | Temporal    | | MinIO (S3)  | | Grafana stack    | |    |
| | | 4GB RAM     | | 4GB RAM     | | 4GB RAM          | |    |
| | +-------------+ +-------------+ +------------------+ |    |
| |                                                       |    |
| | +---------------------------------------------------+ |    |
| | | Workers Patchright/Camoufox x40-60 concurrent     | |    |
| | | 32GB RAM total (~500MB por worker)                | |    |
| | +---------------------------------------------------+ |    |
| |                                                       |    |
| | +---------------------------------------------------+ |    |
| | | API FastAPI + Dashboard Next.js                   | |    |
| | | 4GB RAM total                                     | |    |
| | +---------------------------------------------------+ |    |
| +-------------------------------------------------------+    |
|                                                               |
| +-------------------------------------------------------+    |
| | GPU pipelines (RTX 5090, 32GB VRAM)                   |    |
| | - AI music generation local (Stable Audio, MusicGen)  |    |
| | - LLM inference behavioral (Llama 3.3 70B Q4)         |    |
| | - LightGBM GPU training para anomaly model            |    |
| +-------------------------------------------------------+    |
|                                                               |
| +-------------------------------------------------------+    |
| | Backups locales: NAS o USB 8TB                        |    |
| | + Offsite: Backblaze B2 cron diario                   |    |
| +-------------------------------------------------------+    |
+-------------------------------+-------------------------------+
                                |
                    +-----------v------------+
                    | VPS offshore $5/mes    |
                    | (Hetzner CCX13 / Vultr)|
                    | - WireGuard egress     |
                    | - Cloudflare Tunnel    |
                    | - Frontend de IP publica|
                    +------------------------+
                                |
                                v
                +--------------------------------+
                | DSPs / Banking / Distros       |
                | (ven la IP del VPS, no la tuya)|
                +--------------------------------+
```

---

## 3. Riesgos asumidos

Al elegir single-node home production, aceptas:

| Riesgo | Severidad | Mitigacion en este doc |
|---|---|---|
| **IP residencial trazable a tu nombre** | CRITICO | WireGuard tunnel a VPS offshore (seccion 4) |
| **SPOF hardware** (un fallo = 100% downtime) | ALTO | UPS + backups offsite + plan recovery 24h |
| **SPOF location** (raid policial fisico) | ALTO | Encripcion LUKS full disk + kill switch fisico (seccion 9) |
| **Uptime ISP residencial** (~98-99%) | MEDIO | Failover 4G + UPS |
| **No HA**: deploys = downtime | MEDIO | Ventanas de mantenimiento programadas (4-6 AM local) |
| **No geo redundancia** para cuentas | MEDIO | Granja modems sigue siendo geo-distribuida (Lithuania/Bulgaria/Vietnam) |
| **Backups locales = 1 punto fisico** | MEDIO | Backblaze B2 offsite (seccion 8) |
| **Bandwidth ISP** (~100-300 Mbps) | BAJO | Suficiente para 50-100 workers |
| **Termal sostenido 24/7** | BAJO | LC-360 + 5 fans manejan; monitorea con sensors |

**Lo que NO puedes mitigar en single-node**:
- Confiscacion fisica del hardware. Si llega un raid, pierdes TODO el catalogo + cuentas + private keys. Backups offsite cifrados con clave que NO esta en la maquina son tu unico parachute.
- Seguro de hardware: si un componente muere, tienes que repararlo TU. En cloud el provider hace el reemplazo en minutos.

---

## 4. Stack OPSEC obligatorio (no skipear)

### 4.1 VPS offshore para egress

**Por que**: TODO trafico saliente hacia DSPs, banking, distribuidor DEBE tener IP que no sea la tuya residencial. Spotify Beatdapp correlaciona IP con identidad facilmente; tu IP peruana residencial es trivialmente trackable a tu RUC/nombre.

**Setup**:

```bash
# 1. Compra VPS Hetzner CCX13 ($4.49/mes) en Helsinki o Falkenstein
#    O Vultr Compute $6/mes en Frankfurt
#    Page con cripto via Bitwage o BitPay si quieres anonimizar

# 2. En el VPS, instala WireGuard server
ssh root@VPS_IP
apt update && apt install -y wireguard-tools iptables-persistent

# 3. Genera keys VPS (server) + workstation (client)
wg genkey | tee server.priv | wg pubkey > server.pub
wg genkey | tee client.priv | wg pubkey > client.pub

# 4. /etc/wireguard/wg0.conf en VPS:
cat <<EOF > /etc/wireguard/wg0.conf
[Interface]
Address    = 10.20.0.1/24
ListenPort = 51820
PrivateKey = $(cat server.priv)
PostUp     = iptables -t nat -A POSTROUTING -s 10.20.0.0/24 -o eth0 -j MASQUERADE
PostDown   = iptables -t nat -D POSTROUTING -s 10.20.0.0/24 -o eth0 -j MASQUERADE

[Peer]
PublicKey  = $(cat client.pub)
AllowedIPs = 10.20.0.2/32
EOF
sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
systemctl enable --now wg-quick@wg0
```

```bash
# 5. /etc/wireguard/wg0.conf en TU WORKSTATION:
sudo tee /etc/wireguard/wg0.conf <<EOF
[Interface]
Address    = 10.20.0.2/24
PrivateKey = <client.priv>
DNS        = 1.1.1.1, 9.9.9.9

[Peer]
PublicKey  = <server.pub>
Endpoint   = VPS_IP:51820
AllowedIPs = 0.0.0.0/0      # routea TODO trafico via VPS
PersistentKeepalive = 25
EOF

# 6. Activa
sudo systemctl enable --now wg-quick@wg0

# 7. Valida que tu IP saliente ahora es la del VPS
curl https://api.ipify.org
# Debe devolver la IP del VPS, NO tu IP residencial
```

**CRITICO**: docker-compose debe heredar el routing del host. Verifica:

```bash
docker run --rm alpine sh -c "apk add curl && curl -s https://api.ipify.org"
# Debe devolver la IP del VPS
```

Si docker no respeta el tunnel, anade `network_mode: host` a workers en compose o crea network bridge custom con default gateway = 10.20.0.1.

### 4.2 Encripcion de disco completa (LUKS)

Si no instalaste Ubuntu con LUKS, **reinstala**. El `cryptsetup` post-instalacion es complejo y propenso a fallos.

```bash
# Durante instalacion Ubuntu Server 24.04:
# - "Install Ubuntu Server" -> "Use entire disk and set up LVM" -> "Encrypt LVM"
# - Passphrase fuerte (entropy >= 80 bits, ej. 6 palabras diceware)
```

**OPSEC tip**: passphrase NO en gestor de contraseñas online. Tatuala en tu memoria via spaced repetition (Anki) o physical key store (paper hidden).

### 4.3 Cloudflare Tunnel para inbound

NUNCA expongas tu IP residencial al internet abriendo puertos. El dashboard se publica via Cloudflare Tunnel (instalado en el VPS):

```bash
# En el VPS offshore
cloudflared tunnel login
cloudflared tunnel create streaming-bot-home
cloudflared tunnel route dns streaming-bot-home dashboard.tudominio.com

# Config /etc/cloudflared/config.yml
cat <<EOF > /etc/cloudflared/config.yml
tunnel: streaming-bot-home
credentials-file: /root/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: dashboard.tudominio.com
    service: http://10.20.0.2:3000   # tu workstation via wireguard
  - hostname: api.tudominio.com
    service: http://10.20.0.2:8000
  - service: http_status:404
EOF

systemctl enable --now cloudflared
```

Resultado: usuarios acceden a `dashboard.tudominio.com` -> Cloudflare -> Tunnel -> VPS -> WireGuard -> tu workstation. Tu IP nunca aparece.

### 4.4 Firewall workstation

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow in on wg0    # solo trafico WireGuard
sudo ufw deny in on enp+   # bloquea LAN local si compartes red
sudo ufw enable
```

### 4.5 SSH solo via WireGuard

Edita `/etc/ssh/sshd_config`:
```
ListenAddress 10.20.0.2
PermitRootLogin no
PasswordAuthentication no
```

```bash
sudo systemctl restart ssh
```

Asi solo puedes SSH desde otra maquina con WireGuard configurado al mismo VPS.

---

## 5. Setup paso a paso

### 5.1 OS recomendado

- **Ubuntu Server 24.04 LTS** (NO desktop). Si quieres GUI ocasional, instala XFCE encima.
- LUKS full disk durante instalacion (seccion 4.2).
- Solo usuario `op` no-root con sudo.
- Hostname: `ops-home-01` (no uses tu nombre real).

### 5.2 Particionado disco

Con 4x 1TB NVMe, recomiendo **LVM sobre LUKS** con esta distribucion:

```
/dev/nvme0n1: sistema + LUKS root (200GB usable, resto LV)
/dev/nvme1n1: data postgres (1TB LV pg_data)
/dev/nvme2n1: data clickhouse (1TB LV ch_data)
/dev/nvme3n1: data minio + sessions + artifacts (1TB LV objects)
```

Si tu motherboard soporta solo 3 NVMe, usa el 4to en M.2 PCIe adapter o relegalo a backup local.

### 5.3 Instala dependencias base

```bash
# Docker + compose
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker op

# uv para Python
curl -LsSf https://astral.sh/uv/install.sh | sh

# Node + pnpm
curl -fsSL https://fnm.vercel.app/install | bash
fnm install 22
npm install -g pnpm@10

# NVIDIA drivers + CUDA + container toolkit (para GPU pipelines)
sudo apt install -y nvidia-driver-565 nvidia-cuda-toolkit
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Verifica GPU disponible en docker
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi
# Debe mostrar tu RTX 5090

# Otros utiles
sudo apt install -y htop iotop nethogs glances tmux git
```

### 5.4 Clona repo y configura

```bash
cd /opt
sudo mkdir streaming-bot && sudo chown op:op streaming-bot
git clone <tu-fork> streaming-bot
cd streaming-bot

# Backend env
cp .env.example .env
nano .env   # ver getting-started.md seccion 4.A

# Genera master key
python3 -c "from cryptography.fernet import Fernet; print('SB_STORAGE__MASTER_KEY=' + Fernet.generate_key().decode())" >> .env

# Compose env
cd infra/compose
cp .env.example .env
nano .env   # rellena passwords PRODUCTION (largos y unicos)

# Dashboard env
cd ../../dashboard
cp .env.example .env.local
nano .env.local
```

### 5.5 Levanta el stack single-node

```bash
cd /opt/streaming-bot/infra/compose

# Usa el compose specific de single-node (creado en seccion siguiente)
docker compose -f single-node.yml --env-file .env up -d

# Espera ~3 min, valida
docker compose -f single-node.yml ps
docker compose -f single-node.yml logs -f --tail=50
```

### 5.6 Migra DB

```bash
cd /opt/streaming-bot
uv sync --extra dev --extra temporal --extra ml --extra api --extra meta --extra captcha --extra stealth

# Migraciones Postgres
export SB_DATABASE__URL="postgresql+asyncpg://app:$(grep POSTGRES_PASSWORD infra/compose/.env | cut -d= -f2)@localhost:5432/streaming_bot"
uv run alembic upgrade head

# Schema ClickHouse
docker exec -i clickhouse clickhouse-client -u app --password "$(grep CLICKHOUSE_PASSWORD infra/compose/.env | cut -d= -f2)" --multiquery < infra/compose/clickhouse/init.sql
```

### 5.7 Arranca workers + API + dashboard

```bash
# Tres procesos en tmux/systemd

tmux new -s api
uv run --extra api uvicorn streaming_bot.presentation.api.server:app --host 127.0.0.1 --port 8000 --workers 4
# Ctrl+B D (detach)

tmux new -s temporal-worker
uv run --extra temporal python -m streaming_bot.infrastructure.temporal.temporal_worker
# Ctrl+B D

tmux new -s dashboard
cd /opt/streaming-bot/dashboard && pnpm install && pnpm build && pnpm start
# Ctrl+B D
```

**Mejor**: convierte cada uno en service systemd para resilencia (ver seccion 5.8).

### 5.8 Servicios systemd

```bash
# /etc/systemd/system/streaming-bot-api.service
sudo tee /etc/systemd/system/streaming-bot-api.service <<EOF
[Unit]
Description=streaming-bot API
After=docker.service network-online.target wg-quick@wg0.service
Wants=docker.service network-online.target

[Service]
Type=simple
User=op
WorkingDirectory=/opt/streaming-bot
EnvironmentFile=/opt/streaming-bot/.env
ExecStart=/home/op/.local/bin/uv run --extra api uvicorn streaming_bot.presentation.api.server:app --host 127.0.0.1 --port 8000 --workers 4
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Repite para temporal-worker y dashboard. Activa:
sudo systemctl daemon-reload
sudo systemctl enable --now streaming-bot-api streaming-bot-temporal streaming-bot-dashboard
```

---

## 6. Aprovechamiento GPU RTX 5090

Tu tarjeta es **el componente mas infrautilizado** si no la usas para AI/ML local. 32GB VRAM = puedes correr modelos que requieren GPUs de $3-5k:

### 6.1 Generacion AI music local (sin pagar Suno)

**Modelos open source 2026**:

| Modelo | VRAM requerida | Calidad | Velocidad RTX 5090 |
|---|---|---|---|
| **Stable Audio Open** | 8GB | Buena (loops 47s) | ~5s por loop |
| **MusicGen Large** (Meta) | 16GB | Muy buena (30s tracks) | ~30s por track |
| **AudioLDM 2** | 12GB | Buena (texto a audio) | ~15s por track |
| **MAGNeT** (Meta) | 12GB | Muy buena, paralelo | ~20s por track |

**Setup MusicGen Large** (recomendado, mejor calidad):

```bash
cd /opt/streaming-bot
uv sync --extra dev
uv pip install audiocraft transformers accelerate

# Test
uv run python <<EOF
from audiocraft.models import MusicGen
import torch

model = MusicGen.get_pretrained('facebook/musicgen-large', device='cuda')
model.set_generation_params(duration=30)
descriptions = ['lo-fi hip hop chill beat', 'ambient forest nature sounds', 'sleep music piano']
wav = model.generate(descriptions)
print(f"Generated {len(wav)} tracks, shape: {wav.shape}")
EOF
```

**Implementacion como adapter**:

Crea `src/streaming_bot/infrastructure/catalog_pipeline/musicgen_local_generator.py` (no esta en el repo aun, es trabajo futuro) que implementa `IAIMusicGenerator` corriendo MusicGen local. **Beneficio**: cero coste por track AI generation = puedes producir 1000+ tracks/mes sin pagar Suno API ($30-100/mes savings).

**Calculo de capacidad**:
- MusicGen Large: 30s track en ~30s GPU = 1 track/min = **1.440 tracks/dia teorico**
- Realista (incluyendo masterizacion ffmpeg + metadata + cover): **300-500 tracks/dia**
- Para tu objetivo de 50-500 tracks/MES: usas la GPU el **2-5%** del tiempo. Resto puedes usarla para:

### 6.2 LLM local para behavioral decisions

Llama 3.3 70B Q4_K_M (40GB) NO entra en 32GB. Pero estos SI:

| Modelo | VRAM | Uso recomendado |
|---|---|---|
| **Llama 3.3 70B Q3_K_M** | 32GB | Decision delays sofisticados, captions Reels, metadata SEO premium |
| **Mistral Small 3 24B Q5** | 18GB | Comentarios automaticos IG, captions, micro-decisions |
| **Qwen 2.5 32B Coder Q4** | 22GB | Auto-generar selectores Patchright cuando un sitio cambie DOM |

Setup via **Ollama** (mas simple):

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.3:70b-instruct-q3_K_M
ollama serve   # API en localhost:11434
```

Implementacion adapter: `OllamaDelayPolicy` que extiende `DecisionDelayPolicy` con backend Ollama local en lugar de OpenAI API. **Savings**: $20-50/mes en OpenAI tokens.

### 6.3 LightGBM con GPU acceleration

Tu modelo de anomaly detection puede entrenarse 3-10x mas rapido con GPU:

```bash
# LightGBM con GPU en lugar de CPU
uv pip install lightgbm --config-settings=cmake.define.USE_GPU=ON
# Verifica:
uv run python -c "import lightgbm; print(lightgbm.basic._LIB.LGBM_GPUVersion())"
```

En `lightgbm_trainer.py`, anade param `device_type='gpu'` al constructor del booster.

### 6.4 Stable Diffusion XL para covers

Sustituye DALL-E 3 ($0.04/cover) por SDXL local:

```bash
uv pip install diffusers torch --extra-index-url https://download.pytorch.org/whl/cu126
```

```python
from diffusers import StableDiffusionXLPipeline
pipe = StableDiffusionXLPipeline.from_pretrained("stabilityai/stable-diffusion-xl-base-1.0", torch_dtype=torch.float16).to("cuda")
image = pipe("lo-fi cover art, anime aesthetic, cozy room, vinyl record, lofi girl style").images[0]
image.save("cover.png")
```

**Savings**: $40-100/mes en DALL-E API si generas 1000+ covers/mes.

### 6.5 Coordinacion GPU (un solo proceso a la vez)

Como tienes 1 GPU, los pipelines deben coordinar acceso. Crea un semaforo file-based o usa Redis lock:

```python
import asyncio
from redis.asyncio import Redis

_GPU_LOCK_KEY = "gpu:rtx5090:lock"

async def with_gpu_lock(redis: Redis, callback, *, timeout: int = 600):
    lock = redis.lock(_GPU_LOCK_KEY, timeout=timeout, blocking_timeout=300)
    if not await lock.acquire():
        raise RuntimeError("gpu lock timeout")
    try:
        return await callback()
    finally:
        await lock.release()
```

Asi MusicGen + SDXL + LightGBM training NUNCA corren al mismo tiempo.

---

## 7. Resource limits y tuning

### 7.1 Memoria total: 96GB DDR5

Con todo arrancado, este es el budget realista:

```
Sistema Ubuntu                  : 4 GB
Postgres 17 (shared_buffers)    : 16 GB
ClickHouse                      : 24 GB
Redis                           : 4 GB
Temporal cluster                : 4 GB
MinIO + workers minio internos  : 2 GB
Grafana stack (Grafana+Loki+Tempo+Prometheus+Alertmanager) : 8 GB
Workers Patchright/Camoufox x40 : 24 GB (600MB cada uno realista)
API FastAPI (4 workers)         : 2 GB
Dashboard Next.js (build+serve) : 2 GB
GPU pipelines (cuando activos)  : 4 GB CPU side
Buffer + cache OS               : 2 GB
TOTAL                           : 96 GB ✓ (apretado pero OK)
```

**Si necesitas mas**: reduce ClickHouse a 16GB, Postgres a 12GB, workers a 30 (suma 24GB libres).

### 7.2 CPU: 24 cores hibridos

Asignacion sugerida via `cpuset` o cgroup limits en docker-compose:

```yaml
postgres:
  deploy:
    resources:
      limits:
        cpus: "6"     # 6 P-cores
clickhouse:
  deploy:
    resources:
      limits:
        cpus: "8"     # 8 cores
worker:
  deploy:
    replicas: 40
    resources:
      limits:
        cpus: "0.4"   # 16 cores compartidos
```

### 7.3 Disco: 4TB NVMe

```
/dev/nvme0n1: sistema + binaries (~500GB usado)
/dev/nvme1n1: postgres data (1TB, monitorea growth)
/dev/nvme2n1: clickhouse data (1TB, esquema TTL 18 meses ya configurado)
/dev/nvme3n1: minio (sessions cifradas + audio masters + logs)
```

Configura `noatime` en /etc/fstab para reducir writes:
```
UUID=... /var/lib/postgresql/data ext4 defaults,noatime,nodiratime 0 2
```

### 7.4 Termal

Workstation 24/7 a sostenido necesita:
- Room AC < 28C (idealmente 22-25C)
- LC-360 lleno con coolant fresco anualmente
- Verifica temps con `sensors` cada hora via cron alerta:

```bash
# /etc/cron.hourly/temp-alert
#!/bin/bash
TEMP=$(sensors | grep "Tctl:" | awk '{print $2}' | tr -d '+°C')
if (( $(echo "$TEMP > 85" | bc -l) )); then
  curl -s -X POST "https://api.telegram.org/bot$TG_TOKEN/sendMessage" \
    -d chat_id=$TG_CHAT -d text="HOT: workstation CPU ${TEMP}C"
fi
```

---

## 8. Backups offsite obligatorios

### 8.1 Que respaldar

| Item | Frecuencia | Donde | TTL |
|---|---|---|---|
| Postgres dump completo | Diario 03:00 | NAS local + Backblaze B2 | 30 dias |
| ClickHouse incremental | Semanal Dom 04:00 | NAS local + Backblaze B2 | 90 dias |
| Sessions cifradas (storage_state) | Diario | NAS local + B2 | 7 dias |
| Master keys (Fernet, WireGuard, Cloudflare) | Una vez + cuando cambien | Paper backup hardware (offline, casa familiar) | Permanente |
| Cuentas DSP credentials (encrypted) | Diario | NAS + B2 | 30 dias |
| Configs `.env` (cifrados con sops/age) | Cuando cambien | Git privado offshore + B2 | Permanente |

### 8.2 Setup Backblaze B2 (cifrado)

```bash
# Crea bucket en https://www.backblaze.com/b2 (cripto-payable)
# Crea Application Key con permisos solo a ese bucket

# Instala restic (mejor que rclone para backups deduplicados + cifrados)
sudo apt install restic

# Inicializa repositorio cifrado
export B2_ACCOUNT_ID=xxxxx
export B2_ACCOUNT_KEY=xxxxx
export RESTIC_REPOSITORY=b2:streaming-bot-backup
export RESTIC_PASSWORD_FILE=/root/.restic-password

# Genera password fuerte y guardala en paper backup ANTES
openssl rand -base64 48 > /root/.restic-password
chmod 600 /root/.restic-password
restic init

# Backup diario
sudo tee /etc/cron.daily/streaming-bot-backup <<EOF
#!/bin/bash
set -euo pipefail
source /opt/streaming-bot/infra/compose/.env

# Postgres dump
docker exec postgres pg_dump -U \$POSTGRES_USER -d \$POSTGRES_DB --format=custom -f /tmp/pg.dump
docker cp postgres:/tmp/pg.dump /var/lib/streaming-bot/backups/pg-$(date +%Y%m%d).dump

# ClickHouse semanal
if [ \$(date +%u) -eq 7 ]; then
  docker exec clickhouse clickhouse-backup create ch-\$(date +%Y%m%d)
fi

# Restic encrypt + upload
restic backup \
  /var/lib/streaming-bot/backups \
  /var/lib/streaming-bot/postgres/storage_state \
  /opt/streaming-bot/.env \
  /opt/streaming-bot/infra/compose/.env \
  /opt/streaming-bot/credentials/ \
  --tag daily

# Cleanup viejos
restic forget --keep-daily 30 --keep-weekly 12 --keep-monthly 6 --prune
EOF
sudo chmod +x /etc/cron.daily/streaming-bot-backup
```

### 8.3 Test recovery (CRITICO)

**Cada mes**, simula recovery:

```bash
restic snapshots
restic restore latest --target /tmp/recovery-test
ls -la /tmp/recovery-test
# Verifica que pg.dump y configs estan ahi y son utiles
```

Sin test recovery, los backups son falsa seguridad.

### 8.4 Paper backup de master keys

En **papel fisico**, guarda en lugar **distinto al de la maquina** (casa familiar, banco safety deposit box):

```
=== STREAMING-BOT MASTER KEYS BACKUP ===
Fecha: 2026-XX-XX

SB_STORAGE__MASTER_KEY (Fernet):
[escribir manuscrito o printed]

LUKS root passphrase:
[escribir manuscrito]

WireGuard client.priv (workstation):
[escribir manuscrito - 44 chars base64]

Restic backup password:
[escribir manuscrito - 64 chars]

Cloudflare API token:
[escribir manuscrito]

VPS root password / SSH key passphrase:
[escribir manuscrito]
```

Si pierdes este papel **Y** te roban la workstation, todo el catalogo y revenue se pierde. Sin paranoia, sin recovery.

---

## 9. Kill switch fisico

Para escenarios de emergencia (raid, sospecha compromise), necesitas matar el sistema **rapidamente** sin que un actor pueda capturar el state runtime.

### 9.1 Hot kill (workstation encendida)

```bash
# Comando unico que ejecuta kill switch software ya implementado
sudo touch /var/lib/streaming-bot/panic.lock
docker compose -f infra/compose/single-node.yml down
shutdown -h now
```

Mejor: boton fisico via USB que ejecute el script. Compra un programmable USB foot pedal (~$20 Aliexpress) y bindea via udev a `/usr/local/bin/panic.sh`.

### 9.2 Cold kill (TRIM + LUKS poweroff)

Si el adversario corta la luz o mueve la maquina:
- LUKS encriptacion en reposo es segura siempre que la passphrase NO este en RAM (apagada).
- TRIM en SSDs hace que datos borrados sean irrecuperables en horas.
- Si tienes UPS, el shutdown limpio se ejecuta antes de quedarse sin bateria. Configura `nut` para auto-shutdown:

```bash
sudo apt install nut
# Configura /etc/nut/ups.conf con tu APC y bateria threshold 10%
```

### 9.3 Plausible deniability disk

Avanzado: **VeraCrypt hidden volume** dentro de un volumen encrypted "decoy". Si te obligan a dar la passphrase en un raid, das la del decoy (que tiene archivos no incriminatorios) y el catalogo real queda inaccesible. Setup complejo, ver `docs/legal/compartmentalization.md` apartado "anti-coercion".

---

## 10. Checklist post-deploy

Tras setup single-node, verifica TODO esto antes de operar productivamente:

### Hardware + sistema
- [ ] LUKS full disk activo (`cryptsetup status nvme0n1_crypt`)
- [ ] UPS conectado, NUT configurado, test de cutoff exitoso
- [ ] AC habitacion mantiene < 26C en pico de carga
- [ ] Sensors temp ok bajo carga sintetica `stress-ng --cpu 24 --timeout 60s`
- [ ] Failover ISP -> 4G testeado (desconecta cable LAN principal, verifica que sigue habiendo internet en 30s)
- [ ] systemd services arrancan en boot (reboot test)

### OPSEC
- [ ] WireGuard tunnel a VPS arriba (`wg show` muestra peer)
- [ ] `curl https://api.ipify.org` devuelve IP del VPS, NO la tuya
- [ ] Docker tambien usa el tunnel: `docker run --rm alpine sh -c "apk add curl && curl https://api.ipify.org"`
- [ ] UFW activo, solo wg0 inbound permitido
- [ ] SSH bindeado a 10.20.0.2, NO a 0.0.0.0
- [ ] Cloudflare Tunnel publica dashboard sin tu IP
- [ ] Backblaze B2 backup test recovery exitoso ultimo mes
- [ ] Paper backup de master keys en location remota

### Software
- [ ] `docker compose -f single-node.yml ps` -> todos los servicios `healthy`
- [ ] `uv run alembic current` muestra cabeza de migraciones aplicada
- [ ] `curl http://10.20.0.2:8000/health` -> `{"status":"ok"}`
- [ ] `curl http://10.20.0.2:9091/metrics` muestra metricas streaming_bot_*
- [ ] Dashboard accessible via `https://dashboard.tudominio.com` y login funciona
- [ ] Temporal UI muestra cluster health: `https://temporal.tudominio.com`
- [ ] `nvidia-smi` muestra RTX 5090 disponible para containers
- [ ] Test smoke E2E: crear job demo TodoMVC y verificar que completa OK

### Operativo
- [ ] Alertas Telegram configuradas y test (CPU temp > 85, container down, anomaly cluster CRITICAL)
- [ ] Cron backup diario verificado (next run shown in `systemctl list-timers`)
- [ ] Cron rotacion credenciales trimestral en calendario
- [ ] Runbook DR-3 (ban masivo cuentas) leido y entendido
- [ ] Kill switch fisico testeado (`touch /var/lib/streaming-bot/panic.lock` mientras corren jobs -> verificar paro inmediato)

---

## 11. Cuando deberias migrar a multi-nodo

Single-node es viable hasta cierto punto. Migra a multi-nodo (Hetzner/cloud) cuando:

| Trigger | Razon |
|---|---|
| Revenue > $30k/mes sostenido | El SPOF empieza a ser inaceptable. Un dia caido = $1k+ perdido |
| Workers concurrent > 80 sostenido | Tu workstation se queda sin headroom CPU/RAM |
| Catalogo > 5.000 tracks | DB y ClickHouse crecen, queries lentas, replicacion necesaria |
| Operadores > 1 (equipo) | Necesitas RBAC real, multiples deploys, staging |
| Banking auditoria seria (Wise compliance check) | Necesitas separar legal/operativo en jurisdicciones |
| Cualquier indicio de targeted attack | Mover a infra anonima offshore inmediatamente |

**Path de migracion**: el repo ya esta listo para multi-nodo (todo el setup Hetzner/Terraform/WireGuard mesh ya documentado en `getting-started.md` seccion 6). La migracion es un fin de semana de trabajo: dump Postgres + ClickHouse, restore en nodos cloud, switch DNS, kill workstation legacy.

---

## Resumen accionable: tu setup home production

```bash
# Hardware adicional ya comprado (UPS + 4G modem + NAS + VPS $5/mes)

# 1. Reinstala Ubuntu Server 24.04 con LUKS full disk
# 2. Setup VPS offshore + WireGuard tunnel
# 3. Setup Cloudflare Tunnel via VPS
# 4. Clona repo
git clone <fork> /opt/streaming-bot
cd /opt/streaming-bot

# 5. Configura .env files (3: backend, dashboard, infra/compose)
# 6. Levanta stack
cd infra/compose && docker compose -f single-node.yml --env-file .env up -d

# 7. Migra
uv sync --extra dev --extra temporal --extra ml --extra api --extra meta --extra captcha --extra stealth
uv run alembic upgrade head

# 8. Activa servicios systemd
sudo systemctl enable --now streaming-bot-api streaming-bot-temporal streaming-bot-dashboard

# 9. Configura backups
sudo /etc/cron.daily/streaming-bot-backup

# 10. Pasa el checklist seccion 10 completo
```

CAPEX adicional: ~S/. 4.700 + S/. 18/mes VPS + S/. 80/mes 4G + $5/mes B2.
**TOTAL recurrente**: ~S/. 117/mes (~$31 USD) **vs $200-400/mes Hetzner**.
**Savings anuales**: ~$2.000-4.500/año.
**Trade-off**: SPOF + OPSEC degradado vs cloud, mitigado al 80% por las medidas anteriores.
