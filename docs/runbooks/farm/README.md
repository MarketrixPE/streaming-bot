# Granja 4G/5G — runbooks operativos

Este modulo cubre la operacion de la granja propia de modems 4G/5G
en colocations Lithuania / Bulgaria / Vietnam, segun el plan
ejecutivo Mes 7-9 (`farm-scale`) y la base operativa de Mes 1
(`mobile-farm-v1`).

## Objetivos operativos de la granja

| KPI | Target |
|-----|--------|
| Modems online en cada locacion | >= 95% del rack instalado |
| Time-to-productive de un rack nuevo | <= 14 dias |
| Costo por slot/dia all-in | <= USD 2.50 (target 2026) |
| Modems con `flagged_count > 5` reemplazados | < 7 dias desde deteccion |
| Rotacion fisica de SIMs flagged | mensual revision |
| Disponibilidad SMS hub por locacion | >= 99.5% (RTO 2h en outage) |
| IPs unicas servidas por modem en 30 dias | >= 5 (rotation healthy) |

## Mapa de documentos

| Documento | Cuando se usa |
|-----------|---------------|
| [`hardware-bom.md`](./hardware-bom.md) | Diseno de un rack nuevo (50 modems base). Procurement. |
| [`colo-providers.md`](./colo-providers.md) | Decision proveedor colo en cada pais. Negociacion contratos. |
| [`scaling-playbook.md`](./scaling-playbook.md) | Mes 7, 8, 9: extensiones a 200, 300, 500 modems. |
| [`operations-daily.md`](./operations-daily.md) | Operativa diaria del operador o ops tecnico in-situ. |
| [`troubleshooting.md`](./troubleshooting.md) | Top 10 fallos con diagnostico + fix. |

## Mapa de scripts

| Script | Frecuencia | Trigger |
|--------|------------|---------|
| [`infra/scripts/farm/provision-modem.sh`](../../../infra/scripts/farm/provision-modem.sh) | On-demand | Rack nuevo, modem reemplazado |
| [`infra/scripts/farm/rotate-flagged-sim.sh`](../../../infra/scripts/farm/rotate-flagged-sim.sh) | Diario via cron | Mantenimiento preventivo |

## Topologia tipica de un rack

```
                    Internet (proveedor colo, fibra simetrica)
                              |
                    +---------+---------+
                    | Mikrotik CCR2004 (router)
                    +---------+---------+
                              |
                    +---------+---------+
                    | Mikrotik CRS328 (24p switch)
                    +---------+---------+
                              |
        +----------+----------+----------+----------+
        |          |          |          |          |
+-------+--+ +-----+----+ +---+------+ +---+------+
| Servidor | | UPS APC  | | Powered  | | Powered  |
| Dell R730| | SmartUPS | | USB hub  | | USB hub  |
| 256GB RAM| | 1500     | | x4       | | x4       |
| 4TB NVMe | | (15 min) | |          | |          |
+----------+ +----------+ +----+-----+ +----+-----+
                               |            |
                          +----+----+--+    |
                          | Quectel modems x N (50 inicial)
                          +-------------+
```

## Compartmentalizacion farm

> Detalle completo en `docs/legal/compartmentalization.md` capa 6.

- Granja contratada via shell company local en cada pais
  (UAB en Lithuania, OOD en Bulgaria, Cong Ty TNHH en Vietnam).
- Pagos al colo y al proveedor SIM via cuenta local de la shell, NO
  via cuenta del holding ni del Wyoming/Estonia operativo principal.
- Acceso SSH al farm host SOLO via WireGuard del control plane;
  jamas exponer SSH al internet abierto.
- Direccion fisica de la shell local NO debe coincidir con el
  registered office del holding patrimonial ni con direccion
  personal del operador.

## Compromisos contractuales tipicos con colo

| Item | Negociar |
|------|----------|
| SLA uplink | >= 99.95% mensual |
| Bandwidth incluido | >= 1 Gbps simetrico, sin caps si pagas premium |
| Power redundancia | A+B feeds + UPS local del rack (A+B opcional segun colo) |
| Crossconnect a IXP local (LIX, BIX, VNIX) | incluido o EUR/USD 30-60/mes |
| Penalty por SLA breach | credit en factura proximo mes (pisotear bien en contract) |
| Acceso fisico hands & remote | minimo 2h/mes incluido en plan, EUR 60-120/h adicional |
| Almacenamiento 4G/5G antenas en techo (si necesario) | clausula explicita; muchos colos no permiten antenas extra |
| Salida del contrato | minimo 30 dias notice, sin penalty al cabo de 12 meses |

## Salud financiera de la granja

OPEX tipica all-in por modem/dia (target):

```
Hardware amortizado (5 anos lifetime modem + servidor): 0.30
SIM data 4G/5G (Lithuania Bite EUR 5/mes/SIM ~30 dias):   0.18
Energia (~3W modem + colo overhead):                       0.10
Colo cost por U distribuido sobre modems:                  0.15
Bandwidth (~3 GB/dia/modem promedio):                      0.05
SMS hub host amortizado:                                   0.05
Overflow SIM rotation (1 SIM/modem cada 90 dias):          0.10
Hands-and-eye remoto (1h/modem/anio):                      0.10
Mantenimiento preventivo (30 dias hands operador local):   0.50
Software ops (parte amortizada del salario admin):         0.40
                                                          -----
                                                  TOTAL:  ~1.93
```

Target 2026: < USD 2.50/slot/dia all-in. Above 3.00 = revisar
provider mix. Above 4.00 = volver a proveedores externos como
ProxyEmpire mobile + 5SIM (no granja propia).

## Referencias clave

- Hetzner Server Auction (precio Dell/Supermicro usados): <https://www.hetzner.com/sb>.
- Quectel EG25-G datasheet: <https://www.quectel.com/product/lte-eg25-g/>.
- Mikrotik CRS328-24P-4S+RM: <https://mikrotik.com/product/crs328_24p_4s_rm>.
- StarTech ST7300UPB powered USB hub: <https://www.startech.com/en-us/cards-adapters/st7300upb>.
- LIX (Lithuania IXP): <https://www.lix.lt/>.
- BIX.bg (Bulgaria IXP): <https://www.bix.bg/>.
- VNIX (Vietnam IXP): <https://vnix.vn/>.
