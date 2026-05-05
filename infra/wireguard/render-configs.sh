#!/usr/bin/env bash
# Genera configs WireGuard wg0.conf por nodo a partir de plantilla + claves.
# Variables requeridas: CONTROL_IP, DATA_IP, WORKERS_IP (IPs publicas).
set -euo pipefail

cd "$(dirname "$0")"
: "${CONTROL_IP:?Define CONTROL_IP=public IP de node-control}"
: "${DATA_IP:?Define DATA_IP=public IP de node-data}"
: "${WORKERS_IP:?Define WORKERS_IP=public IP de node-workers}"

CONTROL_PRIV=$(<keys/control.priv)
CONTROL_PUB=$(<keys/control.pub)
DATA_PRIV=$(<keys/data.priv)
DATA_PUB=$(<keys/data.pub)
WORKERS_PRIV=$(<keys/workers.priv)
WORKERS_PUB=$(<keys/workers.pub)

# ── node-control (10.10.0.10) ────────────────────────────────────────────
cat > wg0-control.conf <<EOF
# WireGuard wg0.conf para node-control
[Interface]
Address    = 10.10.0.10/24
ListenPort = 51820
PrivateKey = ${CONTROL_PRIV}

[Peer]
# node-data
PublicKey  = ${DATA_PUB}
Endpoint   = ${DATA_IP}:51820
AllowedIPs = 10.10.0.20/32
PersistentKeepalive = 25

[Peer]
# node-workers
PublicKey  = ${WORKERS_PUB}
Endpoint   = ${WORKERS_IP}:51820
AllowedIPs = 10.10.0.30/32
PersistentKeepalive = 25
EOF

# ── node-data (10.10.0.20) ───────────────────────────────────────────────
cat > wg0-data.conf <<EOF
[Interface]
Address    = 10.10.0.20/24
ListenPort = 51820
PrivateKey = ${DATA_PRIV}

[Peer]
# node-control
PublicKey  = ${CONTROL_PUB}
Endpoint   = ${CONTROL_IP}:51820
AllowedIPs = 10.10.0.10/32
PersistentKeepalive = 25

[Peer]
# node-workers
PublicKey  = ${WORKERS_PUB}
Endpoint   = ${WORKERS_IP}:51820
AllowedIPs = 10.10.0.30/32
PersistentKeepalive = 25
EOF

# ── node-workers (10.10.0.30) ────────────────────────────────────────────
cat > wg0-workers.conf <<EOF
[Interface]
Address    = 10.10.0.30/24
ListenPort = 51820
PrivateKey = ${WORKERS_PRIV}

[Peer]
# node-control
PublicKey  = ${CONTROL_PUB}
Endpoint   = ${CONTROL_IP}:51820
AllowedIPs = 10.10.0.10/32
PersistentKeepalive = 25

[Peer]
# node-data
PublicKey  = ${DATA_PUB}
Endpoint   = ${DATA_IP}:51820
AllowedIPs = 10.10.0.20/32
PersistentKeepalive = 25
EOF

chmod 600 wg0-control.conf wg0-data.conf wg0-workers.conf
echo "Generados:"
ls -la wg0-*.conf
