# SMS Hub — granja de modems

Servicio FastAPI standalone que se despliega EN el nodo de la granja
(Lithuania / Bulgaria / Vietnam) y expone una API tipo "5SIM-lite" al
control plane.

## Endpoints

```
POST   /numbers/rent           # alquila un E.164 de un modem libre del pais
DELETE /numbers/{sid}          # libera el numero
GET    /numbers/{sid}/sms      # long-poll por SMS entrante
GET    /modems                 # listado salud de modems
GET    /healthz                # health endpoint para Cloudflare
```

Autenticacion: `Authorization: Bearer <API_TOKEN>` (compartido con el
control plane via env var).

## Diseno

```
+--------------------+
| FastAPI hub server |
+----------+---------+
           |
           |  postgres + redis
           v
+--------------------+
| SmsInbox + Numbers |
| persistentes       |
+--------------------+
           ^
           |  +CMTI URC events
           |
+--------------------+
|  modem daemons     |  un proceso por modem (systemd)
|  (pyserial)        |  suscribe URC AT, persiste SMS
+--------------------+
           ^
           |  serial /dev/ttyUSB*
+--------------------+
| Modems Quectel x50 |
+--------------------+
```

## Despliegue

```sh
cd /opt/streaming-bot/infra/sms_hub
docker build -t streaming-bot/sms-hub:latest .
docker run -d --name sms-hub \
  -e SMS_HUB_TOKEN=$SMS_HUB_TOKEN \
  -e DATABASE_URL=postgresql://...@10.10.0.20:5432/sms_hub \
  -p 10.10.0.30:8090:8090 \
  --network host \
  streaming-bot/sms-hub:latest

# Daemon por modem (uno por dispositivo serie):
for port in /dev/ttyUSB2 /dev/ttyUSB6 /dev/ttyUSB10 ...; do
  systemctl enable --now sms-hub-modem@$(basename $port).service
done
```

Ver `daemon/sms_modem_daemon.py` para el cliente serial que escucha URC.

## Cron de housekeeping

```cron
# auto-release de numeros sin SMS en 30 min
*/5 * * * * /opt/streaming-bot/infra/sms_hub/scripts/housekeeping.sh
```
