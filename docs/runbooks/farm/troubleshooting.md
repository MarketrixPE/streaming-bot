# Troubleshooting — top 10 fallos comunes en granja

> Cada fallo: sintoma observado / diagnostico / fix concreto /
> prevencion. Ordenados por frecuencia esperada en operacion 2026.

## #1 — USB power surge: hub StarTech entra en proteccion

### Sintoma
- Multiples modems del mismo USB hub aparecen offline al mismo
  tiempo.
- En `lsusb` host: el hub StarTech NO aparece, o aparece con
  "current bDeviceClass" cero.
- Logs `dmesg` muestran "USB disconnect" simultaneo de N puertos.

### Diagnostico
```sh
ssh root@farm-${FARM}.<entity-domain>
dmesg -T | tail -200 | grep -E 'usb|hub' | tail -50

# Identifica el hub afectado (bus/device)
lsusb -t

# Power consumption (si NMC del UPS expone via SNMP)
snmpget -v2c -c public ups.local PowerNet-MIB::upsBasicOutputCurrent.0
```

### Fix
1. Power-cycle del hub: desconectar USB del hub del host, esperar
   30s, reconectar.
   ```sh
   # Si tienes uhubctl instalado y el hub lo soporta (StarTech ST7300UPB
   # responde a per-port toggle pero el master toggle es manual)
   uhubctl -l 2-3 -a cycle
   ```
2. Si persiste: el hub esta defectuoso, reemplazar por spare.
3. Investigar root cause: total amperage en el rack supero los
   bounds del UPS o del hub power supply.

### Prevencion
- Limitar a 6 modems por hub StarTech (en lugar de los 7 max,
  para tener headroom).
- Verificar peak current draw del UPS via NMC: si pasa el 70% de
  capacidad, anadir UPS adicional.
- Power supply del hub debe ser 12V/4A; si vino con 12V/2.5A es
  insuficiente.

---

## #2 — Modem stuck en airplane mode

### Sintoma
- Modem deja de responder a AT commands con OK.
- `at+cfun?` retorna `+CFUN: 0` (modulo en min functionality
  mode).
- No se conecta a la red (no SMS, no datos).

### Diagnostico
```sh
ssh root@farm-${FARM}.<entity-domain>
# Identifica el puerto del modem
echo "ATI" | atinout - /dev/ttyUSB42 -

# Estado actual
echo "AT+CFUN?" | atinout - /dev/ttyUSB42 -
# Si retorna +CFUN: 0 -> stuck en airplane

# Estado red
echo "AT+CREG?" | atinout - /dev/ttyUSB42 -
# Esperado: +CREG: 0,1 (registered home) o +CREG: 0,5 (roaming)
```

### Fix
```sh
# Forzar full functionality mode
echo "AT+CFUN=1,1" | atinout - /dev/ttyUSB42 -
# El modem se reinicia, esperar 30s

# Validar
sleep 30
echo "AT+CFUN?" | atinout - /dev/ttyUSB42 -
echo "AT+CREG?" | atinout - /dev/ttyUSB42 -

# Si AT+CFUN=1,1 no arregla: power-cycle USB
uhubctl -l 2-3 -p 4 -a cycle  # ejemplo, port 4 del hub bus 2-3
```

### Prevencion
- Configurar autostart con `AT+CFUN=1` post-boot via daemon
  `sms-hub-modem@.service`.
- Monitor `AT+CFUN?` cada 5 min como Prometheus exporter desde
  el daemon.

---

## #3 — IMEI flagged por DSP (cuentas asociadas baneadas)

### Sintoma
- `flagged_count` del modem incrementa rapidamente.
- Cuentas creadas o usadas en ese modem terminan en `state='banned'` con
  alta tasa.

### Diagnostico
```sh
$PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
SELECT
  m.imei,
  m.flagged_count,
  COUNT(DISTINCT a.id) FILTER (WHERE a.state='banned') AS bans_via_modem,
  COUNT(DISTINCT a.id) FILTER (WHERE a.state='active') AS active_via_modem,
  m.last_health_check_at
FROM modems m
LEFT JOIN session_records sr ON sr.modem_id = m.id
LEFT JOIN accounts a ON a.id = sr.account_id
WHERE m.imei = 'AAAAAA-FLAGGED-IMEI'
GROUP BY m.imei, m.flagged_count, m.last_health_check_at;
"

# Comparar IPs servidas (si todas son la misma subnet, signal alta)
$PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
SELECT proxy_used, COUNT(*) AS n
FROM stream_history sh
JOIN session_records sr ON sr.id = sh.session_id
WHERE sr.modem_id = '<modem-uuid>'
GROUP BY proxy_used
ORDER BY n DESC LIMIT 10;
"
```

### Fix
1. Quarantine inmediato del modem:
   ```sh
   $PG psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
   UPDATE modems SET state='quarantined', notes=notes||E'\nflagged-quarantine '||CURRENT_TIMESTAMP
   WHERE imei = 'AAAAAA-FLAGGED-IMEI';
   "
   ```
2. Decision en T+24h:
   - Si solo afectado este IMEI: la SIM esta fingerprintada, rotacion
     fisica de SIM (SI mismo IMEI puede salvarse con SIM nueva limpia).
   - Si IMEI tambien fingerprintado (raro pero posible): IMEI burn,
     reemplazo de hardware.
3. Actualizar el script `rotate-flagged-sim.sh` queue para visita
   on-site.

### Prevencion
- Limitar `max_accounts_per_day` por modem a 3 (default), nunca subir
  > 5 en modems con < 30 dias en operacion.
- Coherent Fingerprint Engine v2 debe variar UA/Client Hints por
  cuenta servida desde el mismo modem.

---

## #4 — SIM block KYC: provider bloquea SIM por verificacion adicional

### Sintoma
- SIM deja de funcionar de un dia a otro sin razon aparente.
- AT+CREG retorna +CREG: 0,3 (registration denied).
- Provider envia SMS al numero "Su tarjeta requiere verificacion KYC,
  visite [URL] o llame [numero]".

### Diagnostico
```sh
# Validar SIM esta fisicamente OK (puede leerse)
echo "AT+CIMI" | atinout - /dev/ttyUSB42 -  # IMSI debe responder
echo "AT+CCID" | atinout - /dev/ttyUSB42 -  # ICCID debe responder

# Si AT+CIMI responde pero AT+CREG: 0,3 -> bloqueo network-side, no SIM-side
```

### Fix
1. Identificar provider y rota inmediato:
   - Bite Lithuania: re-KYC tipicamente requerido si SIM uso > 200 GB
     en pocas semanas (anomalia para "personal data" pretendido).
   - A1 Bulgaria: KYC review aleatorio con baja frecuencia.
   - Viettel Vietnam: state-mandated KYC review periodica.
2. NO completar la KYC con docs reales del operador. Si el contract
   B2B con shell company ya autoriza el data plan, el bloqueo es
   bug del provider o anti-fraud trigger.
3. Contact account manager del provider via shell company:
   "We are reviewing the data usage; please confirm contractual cap"
   y delay deliberado.
4. Si la SIM no se desbloquea en 7 dias: marcar SIM como burnt en
   inventario, ordenar SIM nueva via contract B2B.

### Prevencion
- Monitorizar SIM data quota usage diario (vease operations-daily.md).
- Throttle modem si > 80% del cap a mitad de mes.
- Mantener relacion de account manager con cada provider; un
  contacto humano evita bloqueos automaticos.

---

## #5 — SMS hub NO recibe SMS pero el modem lo registra

### Sintoma
- AT command directo al modem `AT+CMGL="ALL"` muestra SMS recibidos.
- `farm_sms_inbox` en Postgres NO tiene los SMS.
- El daemon `sms-hub-modem@ttyUSBN` aparece running pero stale.

### Diagnostico
```sh
ssh root@farm-${FARM}.<entity-domain>

# Daemon esta corriendo?
systemctl status sms-hub-modem@ttyUSB42.service

# Logs ultimos 100
journalctl -u sms-hub-modem@ttyUSB42.service -n 100

# El SMS parsing fallo? (CMGR header malformed por encoding 8-bit)
echo "AT+CMGR=1" | atinout - /dev/ttyUSB42 -
```

### Fix
1. Restart del daemon:
   ```sh
   systemctl restart sms-hub-modem@ttyUSB42.service
   sleep 5
   systemctl status sms-hub-modem@ttyUSB42.service
   ```
2. Si el SMS contiene caracteres no-ASCII (ej. caracteres lituanos):
   el daemon en `infra/sms_hub/daemon/sms_modem_daemon.py` decode
   con `errors="ignore"`. Verificar que el CMGR header parsing
   acepta encoding UCS-2 (8-bit hex). Si no: ticket dev para fix.
3. Workaround inmediato: leer SMS via AT+CMGL y persistir
   manualmente al inbox via psql.

### Prevencion
- Healthcheck del daemon cada 1 min via cron interno del farm host.
- Alert al ops si daemon no procesa SMS por > 30 min.

---

## #6 — Network: WireGuard mesh peer down

### Sintoma
- Control plane no puede SSH al farm host.
- `ping 10.10.0.30` desde control: timeout.
- BUT: ping a IP publica del farm host: ok.

### Diagnostico
```sh
# Desde control plane
sudo wg show

# Si el peer "farm-lt" muestra last handshake > 3 min, hay fallo
# Interface up?
ip link show wg0
```

### Fix
```sh
# En control plane: forzar handshake
sudo wg set wg0 peer <farm-lt-pubkey> endpoint <farm-lt-public-ip>:51820

# Si persiste: restart wg
systemctl restart wg-quick@wg0

# Si necesitas SSH al farm via internet abierto (last resort):
# usar Cloudflare Tunnel pre-configurado en farm host (puerto 22 detras
# de Tunnel)
ssh -o ProxyCommand='cloudflared access ssh --hostname ssh-farm-lt.<entity-domain>' \
  root@farm-lt
```

### Prevencion
- WireGuard peer keepalive en config: `PersistentKeepalive = 25`.
- Heartbeat Prometheus exporter de cada peer para alerta automatica.
- Backup SSH access via Cloudflare Tunnel (siempre on, jamas exponer
  puerto 22 al internet abierto).

---

## #7 — Modem reporta IP publica statica (no rotation natural)

### Sintoma
- `current_public_ip` del modem no cambia en > 24h.
- Cuentas servidas siempre desde la misma IP, signal alta para DSP.

### Diagnostico
```sh
# Desde el host del modem, pedirle al modem reconectar
ssh root@farm-${FARM}.<entity-domain>

# Ver IP actual
echo "AT+QGDCNT?" | atinout - /dev/ttyUSB42 -  # bytes counter
echo "AT+CGPADDR=1" | atinout - /dev/ttyUSB42 - # IP actual

# Validar que el operador asigna IPs dinamicas (algunos APN B2B son
# CGNAT con IP publica relativamente estable; no es ideal)
```

### Fix
```sh
# Forzar reconexion data: detach + attach
echo 'AT+CGATT=0' | atinout - /dev/ttyUSB42 -
sleep 5
echo 'AT+CGATT=1' | atinout - /dev/ttyUSB42 -
sleep 10
echo 'AT+CGPADDR=1' | atinout - /dev/ttyUSB42 -

# Si la IP sigue igual: el APN del operador es CGNAT estable.
# Solucion: cambiar APN o cambiar SIM por una que rote.
echo 'AT+CGDCONT=1,"IP","internet.bite.lt.dynamic"' | atinout - /dev/ttyUSB42 -

# Algunos operadores rotan IP solo al cambiar de torre celular;
# physical antenna repositioning puede ser unica solucion.
```

### Prevencion
- Antes de comprar SIMs B2B, validar con 5 SIMs test que el APN
  asigna IPs dinamicas con rotacion al menos cada 4-12 horas.
- Mikrotik scheduler que cada 2h fuerza un AT+CGATT=0/1 en cada
  modem (script bash periodico).

---

## #8 — Postgres connection refused desde SMS hub

### Sintoma
- `farm_sms_inbox` no acepta inserts.
- Daemon log muestra `asyncpg.exceptions.ConnectionDoesNotExistError`.

### Diagnostico
```sh
ssh root@farm-${FARM}.<entity-domain>

# Test conexion al Postgres del control plane via WireGuard
psql "postgresql://app:${POSTGRES_PASSWORD}@10.10.0.20:5432/sms_hub" \
  -c "SELECT NOW();"
```

### Fix
1. Si conn timeout: revisar WireGuard mesh (vease #6).
2. Si auth failed: posible que `rotate-credentials.sh` corrio sin
   sync al SMS hub. Re-pull de `.env` desde control plane:
   ```sh
   scp control:/opt/streaming-bot/infra/sms_hub/.env \
     root@farm-${FARM}.<entity-domain>:/opt/streaming-bot/infra/sms_hub/.env
   systemctl restart sms-hub
   ```
3. Si pgbouncer entre ambos: verificar pgbouncer status y reload.

### Prevencion
- `rotate-credentials.sh` ya incluye paso para sync al SMS hub via
  SSH (ver `rotate_sms_hub` function). Verificar que ejecuta sin
  error en cada rotation.

---

## #9 — UPS battery degradation: runtime menor al esperado

### Sintoma
- UPS reporta runtime de 4 min en condicion plena (esperado 10-12 min).
- En power outage real: shutdown del servidor host antes de tiempo.

### Diagnostico
```sh
# SNMP query al APC SmartUPS via NMC
snmpget -v2c -c public ups.local \
  PowerNet-MIB::upsAdvBatteryRunTimeRemaining.0 \
  PowerNet-MIB::upsAdvBatteryReplaceIndicator.0 \
  PowerNet-MIB::upsAdvBatteryActualVoltage.0

# Si ReplaceIndicator = 1, sustitucion inmediata
# Si Voltage < nominal (24V para SRT1500): degradacion
```

### Fix
1. Reemplazar battery set con APC RBC93 (USD 130 spare in stock).
2. Schedule visita on-site para reemplazo (~ 1h work).
3. Validar runtime post-reemplazo: cargar UPS al 60% y medir.

### Prevencion
- Self-test mensual programado del UPS via NMC.
- Replacement preventivo cada 24-30 meses (battery lifetime APC
  declarado: 3-5 anos, conservar 24-30 para zero risk).

---

## #10 — Daemon `sms-hub-modem@.service` crash loop

### Sintoma
- `systemctl status sms-hub-modem@ttyUSBN` muestra `restart=always`
  pero el servicio entra y sale cada 10-30s.

### Diagnostico
```sh
journalctl -u sms-hub-modem@ttyUSB42.service --since "10 minutes ago"

# Buscar Python tracebacks
journalctl -u sms-hub-modem@ttyUSB42.service -n 500 \
  | grep -A 20 'Traceback'
```

### Causas frecuentes
- Permisos: el user del service NO tiene access a /dev/ttyUSB42.
  Fix: `chmod a+rw /dev/ttyUSB42` o anadir user al grupo `dialout`.
- Modem se desconectado pero el path persiste: hay un device dead
  pero `/dev/ttyUSB42` apunta a nada. Fix: udev reload + mejor uso
  de `/dev/serial/by-id/usb-Quectel_EG25-G_<serial>` que es estable.
- Postgres CONN string invalido tras `rotate-credentials.sh`. Fix:
  re-sync `.env` (vease #8).

### Fix template
```sh
# Verificar permisos
ls -la /dev/ttyUSB42

# Re-mount con stable path
udevadm control --reload-rules
udevadm trigger

# Editar service unit para usar by-id stable path
sed -i 's|/dev/ttyUSB42|/dev/serial/by-id/usb-Quectel_EG25-G_FAFAFAFA-if00-port0|' \
  /etc/systemd/system/sms-hub-modem@.service
systemctl daemon-reload
systemctl restart sms-hub-modem@ttyUSB42.service
```

### Prevencion
- Udev rules para mapear cada modem a un device path estable
  basado en IMEI (pre-configurar al provisioning):
  ```
  # /etc/udev/rules.d/99-modems.rules
  SUBSYSTEM=="tty", ATTRS{idVendor}=="2c7c", ATTRS{idProduct}=="0125", \
    ATTRS{serial}=="<modem-serial>", SYMLINK+="modem-<imei>"
  ```

---

## Tabla resumen frecuencia esperada (en granja 300 modems)

| Issue | Frecuencia esperada |
|-------|---------------------|
| #1 USB power surge | 1-2 veces/mes |
| #2 Modem stuck airplane | 5-10 veces/mes (recuperable via AT+CFUN) |
| #3 IMEI flagged por DSP | 5-15 modems/mes (rotacion) |
| #4 SIM block KYC | 1-3 SIMs/mes |
| #5 SMS hub no procesa SMS | 1-2 veces/mes |
| #6 WireGuard mesh down | < 1 vez/trimestre |
| #7 IP publica statica | depende del operador SIM |
| #8 Postgres conn refused | 1 vez/trimestre (post-rotation) |
| #9 UPS battery degrade | 1 vez cada 24-30 meses |
| #10 Daemon crash loop | 1-3 veces/mes |
