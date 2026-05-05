#!/usr/bin/env bash
# Genera pares de claves WireGuard para los 3 nodos del mesh.
# Salida: keys/<nodo>.priv y keys/<nodo>.pub
# IMPORTANTE: keys/ esta en .gitignore.
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p keys
chmod 700 keys

for node in control data workers; do
  if [[ -f "keys/${node}.priv" ]]; then
    echo "[skip] keys/${node}.priv ya existe"
    continue
  fi
  wg genkey | tee "keys/${node}.priv" | wg pubkey > "keys/${node}.pub"
  chmod 600 "keys/${node}.priv" "keys/${node}.pub"
  echo "[ok] keys/${node}.priv generada"
done

echo
echo "Public keys:"
for node in control data workers; do
  printf "  %-8s %s\n" "$node" "$(cat keys/${node}.pub)"
done
