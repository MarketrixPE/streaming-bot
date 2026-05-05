#!/usr/bin/env bash
# Bootstrap manual de un nodo recien creado por Terraform.
# Asume cloud-init.yaml ya corrio (docker, wireguard, fail2ban estan).
# Uso: ./bootstrap-node.sh <role>  con role en {control,data,workers}
set -euo pipefail

ROLE="${1:?Uso: $0 {control|data|workers}}"
case "$ROLE" in
  control|data|workers) ;;
  *) echo "Role invalido: $ROLE"; exit 1 ;;
esac

echo "[1/5] Comprobando prerequisitos..."
command -v docker >/dev/null || { echo "docker no instalado"; exit 1; }
docker compose version >/dev/null || { echo "docker compose no disponible"; exit 1; }

echo "[2/5] Creando directorios persistentes..."
mkdir -p /var/lib/streaming-bot/{postgres,clickhouse,redis,minio,prometheus,alertmanager,grafana,loki,tempo,backups}
chown -R 999:999 /var/lib/streaming-bot/postgres
chown -R 101:101 /var/lib/streaming-bot/clickhouse
chown -R 999:999 /var/lib/streaming-bot/redis
chown -R 472:472 /var/lib/streaming-bot/grafana
chown -R 10001:10001 /var/lib/streaming-bot/loki

echo "[3/5] Verificando WireGuard..."
if ! wg show wg0 >/dev/null 2>&1; then
  echo "WARN: wg0 no levantada. Copia /etc/wireguard/wg0.conf y systemctl enable --now wg-quick@wg0"
fi

echo "[4/5] Lanzando stack para role=$ROLE..."
cd /opt/streaming-bot/infra/compose
case "$ROLE" in
  data)
    docker compose -f data-plane.yml --env-file .env up -d
    ;;
  control)
    docker compose -f control-plane.yml --env-file .env up -d
    ;;
  workers)
    docker compose -f workers.yml --env-file .env up -d --scale worker=8
    ;;
esac

echo "[5/5] Status:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
