# WireGuard mesh — streaming-bot

Mesh privada full-mesh entre `node-control` (10.10.0.10), `node-data`
(10.10.0.20) y `node-workers` (10.10.0.30). Subred 10.10.0.0/24 sobre
puerto UDP 51820 (abierto en firewall por Terraform).

## Generar claves

```sh
./gen-keys.sh
```

Crea `keys/control.priv`, `keys/control.pub`, etc. (y los pone en
`.gitignore` localmente — NUNCA commitear).

## Renderizar configs por nodo

```sh
export CONTROL_IP=1.2.3.4   # public IPs reales
export DATA_IP=5.6.7.8
export WORKERS_IP=9.10.11.12
./render-configs.sh
```

Genera `wg0-control.conf`, `wg0-data.conf`, `wg0-workers.conf`.

## Instalar en cada nodo

```sh
scp wg0-control.conf root@$CONTROL_IP:/etc/wireguard/wg0.conf
ssh root@$CONTROL_IP 'chmod 600 /etc/wireguard/wg0.conf && systemctl enable --now wg-quick@wg0'
# repetir para data y workers
```

## Validar

Desde `node-control`:

```sh
ping -c 3 10.10.0.20  # data
ping -c 3 10.10.0.30  # workers
wg show
```
