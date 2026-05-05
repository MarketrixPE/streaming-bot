# Playbook de scaling — 50 -> 200 -> 300 -> 500 modems

> Ejecucion fase Mes 7-9 del plan ejecutivo (`farm-scale`). Cada
> rack nuevo debe ser productivo en <= 14 dias. Asume operador
> principal + 1 tecnico in-situ por pais (contratado durante el
> setup, baja carga continua despues).

## Vision

```
Mes  6 (baseline):  1 rack  Lithuania       50 modems     50 modems totales
Mes  7:            +1 rack  Lithuania      +50 modems    100 modems totales
Mes  8:            +1 rack  Lithuania      +50 modems    150 modems
                   +1 rack  Bulgaria       +50 modems    200 modems totales
Mes  9:            +1 rack  Bulgaria       +50 modems    250 modems
                   +1 rack  Vietnam        +50 modems    300 modems totales
Mes 10-11:         +1 rack  Lithuania      +50 modems    350 modems
                   +1 rack  Bulgaria       +50 modems    400 modems
                   +1 rack  Vietnam        +50 modems    450 modems
Mes 12:            +1 rack  Lithuania      +50 modems    500 modems totales
```

Distribucion final (500 modems Mes 12):

| Pais | Racks | Modems | % de capacidad |
|------|-------|--------|-----------------|
| Lithuania | 4 | 200 | 40% |
| Bulgaria | 3 | 150 | 30% |
| Vietnam | 3 | 150 | 30% |

## Time-to-productive (T2P) por rack

> Target: rack pasa de "hardware en colo" a "100% modems online y
> sirviendo cuentas warming" en 14 dias calendario o menos.

```
T-30 a T-14:  Procurement y SIM activacion (paralelo)
T-14 a T-7:   Hardware shipping + customs
T-7 a T-3:    Recepcion en colo + montaje fisico
T-3 a T-1:    Cableado + power-on + network test
T0:           Productivo: provision-modem.sh ejecutado para 50 modems
T+1 a T+3:    Integration tests con SMS hub + control plane
T+3 a T+14:   Ramp-up gradual de cuentas asignadas
```

## Mes 7: rack #2 Lithuania (extension del rack actual)

### Pre-requisitos
- Rack actual Lithuania ya operativo y > 90% modems online.
- Bites Datacenter Vilnius tiene capacity para 1 rack 2U adicional
  contiguo (preferible para compartir networking: 1 router CCR2004
  puede servir hasta 4 racks).

### Budget previsto

```
Hardware (Quectel modems x50, USB hubs, server, network compartido):
  Modems EG25-G x50:       1,400 USD (sin 5G en este rack secundario)
  USB hubs (8 + spare):      630 USD
  Server: NO necesita nuevo (rack #1 sirve como host)
  Network: NO necesita nuevo (CCR2004 + CRS328 compartidos)
  UPS: + 1 UPS adicional para redundancia: 720 USD
  Fisica + cables:           320 USD
SIMs (Bite, 50 SIMs x EUR 5 x 3 meses): 810 USD
Colo: rack 2U adicional + 5A power: EUR 200/mes (~ USD 218)
Setup fee: EUR 100 (cargo half si contiguo al rack actual)
Labor: tecnico EUR 800 (3 dias)
                                       --------
                              TOTAL: ~ USD 5,500 (rack #2 Lithuania)
```

### Lead times criticos
- Modems Quectel via Antratek EU: 5-10 dias.
- SIMs Bite Verslui activacion 50 nuevas: 7-14 dias.
- Mikrotik gear adicional NO necesario (compartir).

### Checklist T-30 a T0

```
T-30:  RFP a Antratek y Eltrox para 50 EG25-G adicionales (precio + lead time)
T-28:  Confirmar contrato Bite Verslui adicional 50 SIMs (account manager)
T-25:  Order placed: modems + USB hubs + UPS (cobertura entire BOM con 1 PO)
T-25:  Confirmar a Bites Datacenter el contract 2U adicional (firmar adendum)
T-21:  SIMs Bite recibidas y validadas (in-house test 5 SIMs random data acivacion)
T-14:  Hardware delivery a colo (Bites Datacenter recibe directo, evitar transit personal)
T-12:  Tecnico in-situ contratado para 3 dias (T-7 a T-5)
T-10:  Confirmar Mikrotik tiene capacidad de switching (puerto 13-24 libres en CRS328)
T-7:   Tecnico monta hardware, cableado, valida power-on
T-5:   Tecnico valida modem detection (`lsusb` cuenta 50 puertos USB nuevos en host)
T-3:   provision-modem.sh ejecutado para los 50 nuevos IMEIs
T-2:   Validacion SMS hub: alquilar 5 numeros de prueba, validar SMS recibido
T-1:   Smoke test: 1 cuenta nueva creada via warming pipeline en cada uno de 10 modems random
T 0:   Marcar rack como `state='ready'` en Postgres. Ramp-up gradual de cuentas asignadas.
T+7:   Validar 95%+ modems online; si <95% trigger troubleshooting.md
T+14:  Reporte to ops: T2P real medido vs target.
```

## Mes 8: rack #3 Lithuania + rack #4 Bulgaria (replica setup)

### Estrategia
- Rack #3 Lithuania = repeticion exacta del Mes 7 (mismo proveedor,
  misma config, mismas SIMs Bite). 50 modems mas en el mismo
  servidor host (verificar capacidad USB del host: limite efectivo
  es ~ 100 modems por host con USB 3.0 hubs y 1 GB/s aggregate).
  Si > 100 modems por host: anadir 2do server host.

- Rack #4 Bulgaria = primera replicacion en jurisdiccion nueva.
  Mas trabajo: shell company OOD nueva (si no existe), KYC SIMs
  con A1, contrato Telepoint nuevo, nuevo tecnico in-situ.

### Budget Mes 8 (combinado)

```
Rack #3 Lithuania (replica Mes 7):                  ~ USD 5,500
Rack #4 Bulgaria (full setup nuevo pais):
  Shell company OOD setup (si no existe):            ~ USD 1,500
  Hardware (incluye nuevo server + network local):
    Modems x50:                                       1,400
    USB:                                                788
    Server Dell R730:                                 1,400
    Mikrotik CCR2004 + CRS328 (rack standalone):     1,015
    UPS:                                                720
    Fisica:                                             320
  SIMs A1 (50 SIMs, 3 meses):                          580
  Colo Telepoint (caution + setup + 1er mes):          415
  Labor BG (EUR 450 + traduccion contracts):           620
                                                     -------
                                            Subtotal: ~ 8,758
                                                     -------
                                          TOTAL Mes 8: ~ 14,250 USD
```

### Lead times Mes 8

- Shell company OOD Bulgaria: 14-30 dias setup (anticipar Mes 7).
- A1 Bulgaria contract B2B: 5-10 dias.
- Hardware shipping a Sofia: 7-14 dias (UE no aduana).
- Tecnico in-situ Bulgaria: contratacion 7 dias.

### Checklist T-45 a T0 (rack #4 Bulgaria, paralelo al rack #3 LT)

```
T-45:  Iniciar shell company OOD via local agent (Sovereign Group BG o Linklaters BG)
T-30:  RFP a Telepoint Sofia (2U, 1 Gbps, contract 12m)
T-28:  Bank account local OOD abierta (DSK Bank o ProCredit BG, 7-14d)
T-25:  Order hardware (Antratek EU, ship a Sofia direct via Telepoint reception desk)
T-25:  Contract Telepoint firmado, caution paid via OOD bank account
T-21:  Contract A1 BG B2B SIMs firmado, KYC docs presentados
T-14:  Tecnico Bulgaria contratado (fluent BG/EN, ex-ISP background ideal)
T-10:  Hardware delivery Sofia
T-7:   Tecnico monta + cablea (3 dias, EUR 150/dia x 3 + EUR 50 traduccion docs)
T-3:   provision-modem.sh para 50 IMEIs nuevos BG (locale BG)
T-2:   Validacion SMS hub farm-bg.<entity-domain> respondiendo
T-1:   Smoke test cuentas warming en BG modems
T 0:   Mark ready
```

## Mes 9: rack #5 Bulgaria + rack #6 Vietnam

### Rack #5 Bulgaria (replica Mes 8)

Idem rack #4: ~ USD 7,650 (sin shell company setup, ya existe).

### Rack #6 Vietnam (full setup nuevo pais)

```
Shell company Cong Ty TNHH Vietnam setup:           ~ USD 2,500
  (Vietnamese Trading + Tax registration + bank)
Hardware:
  Modems x50:                                       1,400
  USB:                                                788
  Server Supermicro 5028D (mas barato VN):            800
  Mikrotik CCR2004 + CRS328:                       1,015
  UPS APC SRT1500:                                   720
  Fisica:                                             320
SIMs Viettel (50 SIMs, 3 meses):                     450
Colo FPT DC1 Hanoi (caution + setup + 1er mes):      400
Labor VN (USD 350 + traduccion vietnamita docs):     500
                                                   -------
                                          Subtotal: ~ 8,893
                                                   -------
                                        TOTAL Mes 9: ~ USD 16,500 (con rack #5 BG)
```

### Lead times criticos Vietnam

- Shell company Cong Ty TNHH: 30-60 dias setup completo (anticipar
  desde Mes 7). Recomendacion: usar provider local Tilleke & Gibbins
  o Russin & Vecchi.
- Bank account VN: dificil sin presencia fisica del director;
  considerar nominee director con poder restringido firmado al
  inicio del setup.
- Viettel SIM contract: 14-21 dias, requiere docs en vietnamita.
- Hardware shipping a Hanoi: 14-30 dias (aduana VN, declarar como
  "M2M IoT modules" para evitar import duty alto).
- Tecnico in-situ Vietnam: contratacion 14 dias (mas rare encontrar
  English-fluent + ISP background).

### Checklist T-90 a T0 Vietnam (paralelo al rack #5 BG)

```
T-90:  Iniciar shell Cong Ty TNHH (Tilleke & Gibbins lead)
T-60:  Bank account VPBank o Techcombank abierta
T-45:  RFP a FPT DC1 Hanoi
T-40:  Contract FPT firmado, caution paid USD 400
T-30:  Contract Viettel B2B 50 SIMs (docs vietnamita certificados)
T-25:  Hardware order placed (incluye declaracion aduana M2M IoT)
T-21:  Tecnico VN contratado
T-14:  Hardware delivered Hanoi (transit mas largo)
T-10:  SIMs Viettel activadas y entregadas al colo
T-7:   Tecnico monta (3-5 dias en VN, mas tiempo por idioma)
T-3:   provision-modem.sh ejecutado, locale=vi-VN
T-2:   SMS hub farm-vn.<entity-domain> testeado
T-1:   Smoke test cuentas warming
T 0:   Mark ready
```

## Total CAPEX scaling Mes 7-9

```
Mes 7 (rack #2 LT):                ~ USD 5,500
Mes 8 (racks #3 LT + #4 BG):       ~ USD 14,250
Mes 9 (racks #5 BG + #6 VN):       ~ USD 16,500
                                   ----------
            TOTAL CAPEX Mes 7-9:   ~ USD 36,250
```

## OPEX recurrente post-Mes 9 (300 modems)

```
Lithuania (3 racks):
  Colo:  EUR 600/mes  (~ USD 654)
  SIMs:  EUR 750/mes  (~ USD 817)
  Subtotal: ~ USD 1,471/mes

Bulgaria (2 racks):
  Colo:  EUR 320/mes  (~ USD 348)
  SIMs:  EUR 358/mes  (~ USD 390)
  Subtotal: ~ USD 738/mes

Vietnam (1 rack):
  Colo:  USD 175/mes
  SIMs:  USD 150/mes
  Subtotal: ~ USD 325/mes

TOTAL infra colo + SIMs (300 modems): ~ USD 2,534/mes
Costo /modem/dia infra solo: USD 0.281
Anadir overhead operativo (labor + spares + bandwidth overage): + USD 800/mes
TOTAL OPEX: ~ USD 3,334/mes (aprox USD 0.37/modem/dia infra+ops)
Anadir amortizacion CAPEX (~ USD 36k / 36 meses): USD 1,000/mes
TOTAL all-in: ~ USD 4,334/mes (USD 0.48/modem/dia)
```

## Time-to-productive checklist generico (cualquier rack)

> Esta es la checklist DURA para validar que el rack nuevo esta
> dentro del SLA T2P 14 dias.

```
[ ] Day 0: hardware al colo (recepcion confirmada)
[ ] Day 1: power on + network connectivity (ping al control plane)
[ ] Day 2: WireGuard mesh peer establecido (ping al 10.10.0.20)
[ ] Day 3: USB modems detectados (50/50 ports en lsusb)
[ ] Day 4: AT command sanity check (50 modems responden a ATI)
[ ] Day 5: SMS hub levantado y respondiendo /healthz
[ ] Day 6: provision-modem.sh ejecutado para 50 nuevos IMEIs
[ ] Day 7: 50 modems con state='ready' en Postgres
[ ] Day 8: 5 numeros alquilados via SMS hub api responden con SMS
[ ] Day 9: 1 cuenta nueva creada y validada (signup + first stream OK)
[ ] Day 10: 10 cuentas warming asignadas a los 50 modems
[ ] Day 11: ratio actividad ≥ 1 stream/modem/dia (validar throughput)
[ ] Day 12: 0 modems con flagged_count > 0 (validar cleanliness initial)
[ ] Day 13: 25% de cuentas asignadas (rampup planificado)
[ ] Day 14: rack en regimen, 90%+ modems online sirviendo activamente
            -> SLA T2P CUMPLIDO
```

> Si en Day 14 no se cumple: postmortem rack-{N}, identificar
> bottleneck (hardware DOA, SIM activacion lenta, KYC docs pending,
> bug en provision-modem.sh, etc.).

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigacion |
|--------|--------------|---------|------------|
| Hardware DOA > 5% | mediana | reemplazo + 5 dias delay | Stock spare 10% del rack siempre disponible |
| SIM activacion delay > 14 dias | alta en Vietnam | retraso T2P | Negociar SLA con provider; iniciar contract con buffer 21 dias |
| Tecnico in-situ no aparece | baja | cadena retrasa 3-5 dias | Contractor backup pre-identificado (cv en file) |
| Aduana VN retiene hardware | media | retraso 7-14 dias | Declarar correcto como M2M IoT; usar broker aduanal con experiencia |
| Colo Bulgaria pide docs adicionales (Telepoint review) | baja | retraso 5-10 dias | Pre-RFP responses listas + cover letter explicando "data analytics" |
| KYC SIMs A1 BG rechaza shell sin "real" activity | mediana | bloqueo SIM provisioning | Anticipar 30 dias de "actividad real" en cuenta bancaria OOD antes de KYC SIMs (transferencias mock con shell company del operador) |
| Power outage en colo pre-UPS | baja | data loss / cuentas affected | UPS APC + double feed a PDU + bind monitoring SNMP a Prometheus |
| Tecnico in-situ filtra info | baja | OPSEC breach | NDA template signed before hardware access (vease docs/legal/templates/nda-contractor.md) |

## Decision matrix: extension racks Mes 10+

> Cuando llegue Mes 10 con 300 modems:

| Si... | Entonces... |
|-------|-------------|
| Lithuania racks 1-3 estan ≥ 95% online y baneo rate < 5%/mes | Anadir rack #4 Lithuania (Mes 10) |
| Bulgaria racks 4-5 estan estables y revenue dia > USD 100/rack | Anadir rack #5 Bulgaria (Mes 10-11) |
| Vietnam rack #6 muestra revenue marginal por modem inferior a LT | Posponer rack #7 VN, evaluar Indonesia o Mexico |
| Cualquier rack tiene > 30% modems flagged > 5 | NO anadir nuevos hasta corregir; investigar root cause |
| Cualquier pais tiene compliance issue (KYC review masivo, ban del operador SIM) | NO anadir; redirigir capital a otro pais |

## Reporte mensual de scaling

Plantilla a llenar cada mes:

```
Reporte scaling mensual MMYYYY
================================

Modems totales operativos: ___
Modems totales banneados/quarantined: ___
Modems comisionados este mes: ___
Modems decomisionados este mes: ___

Por pais:
  Lithuania:  ___ modems / ___ racks
  Bulgaria:   ___ modems / ___ racks
  Vietnam:    ___ modems / ___ racks

KPIs:
  % modems online (avg): ___% (target ≥ 95%)
  Costo /modem/dia all-in: USD ___ (target ≤ 2.50)
  Revenue /modem/dia: USD ___
  Margin /modem/dia: USD ___
  Anomaly score promedio modems: ___ (target < 0.3)

Cambios planificados proximo mes:
  + N racks en (pais)
  - N modems decomisionados de (pais) por (razon)

Gaps detectados:
  ...

Action items:
  ...
```
