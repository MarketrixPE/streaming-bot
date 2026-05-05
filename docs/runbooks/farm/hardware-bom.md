# Bill of Materials — rack de 50 modems 4G/5G

> Setup base reusable que se replica en Lithuania (Mes 7),
> Bulgaria (Mes 8), Vietnam (Mes 9). Precios verificados Q1 2026,
> con fuente; revisar al hacer procurement.

## Resumen CAPEX inicial por rack (50 modems)

| Categoria | Subtotal USD |
|-----------|--------------|
| Modems Quectel x50 | ~ 1,650 |
| USB hubs powered + extension activos | ~ 600 |
| SIM cards prepago (3 meses inicial) | ~ 750 |
| Servidor host (Hetzner Server Auction) | ~ 700 |
| Networking (router + switch + cables + accesorios) | ~ 980 |
| UPS + accesorios fisicos | ~ 700 |
| Setup colo (caution + 1er mes) | ~ 1,000 |
| Mano de obra setup (instalacion + cabling local 3 dias) | ~ 1,200 |
| **Total CAPEX inicial estimado por rack 50 modems** | **~ 7,580 USD** |

> Con 4 racks (200 modems) Mes 8: ~30k. Con 6 racks Mes 9
> (300 modems Lithuania + Bulgaria + Vietnam): ~45k. Con 10 racks
> (500 modems): ~75k. Numeros conservadores; en regimen el costo
> por slot baja a 1.5x el primer rack por economia de escala
> hardware compartido (servidor host + routing).

## 1. Modems 4G/5G

### Modelo principal: Quectel EG25-G (4G LTE Cat-4)

- Form factor: USB dongle integrado o mini-PCIe via adaptador.
- Categorias: LTE Cat-4 (150 Mbps DL / 50 Mbps UL).
- Soporte global bandeja LTE B1/B2/B3/B5/B7/B8/B20/B28A.
- AT command set completo, soporte URC `+CMTI` para SMS hub.
- Documentacion: <https://www.quectel.com/product/lte-eg25-g/>.

| Proveedor | Precio unitario | MOQ | Lead time | Notas |
|-----------|------------------|------|-----------|-------|
| Aliexpress (vendor B2B verificado) [^1] | USD 28-35 | 1 | 14-30 dias | Riesgo: clones / firmware antiguo. Verifica IMEI rango oficial Quectel. |
| Reseller EU (Antratek NL, Eltrox PL) [^2] | EUR 38-48 | 5 | 5-10 dias | Stock EU, factura B2B, garantia 12m. Recomendado para Lithuania/Bulgaria. |
| Quectel direct distributor (Nordic, Symmetry, Avnet) [^3] | USD 42-55 | 50 | 21-45 dias | Precio MOQ alto pero firmware oficial garantizado. Recomendado para >100 unidades. |

[^1]: Aliexpress Quectel B2B vendors: filtrar por "Trade Assurance" + "Verified Manufacturer". Ej. <https://www.aliexpress.com/wholesale?SearchText=quectel+EG25-G>.
[^2]: Antratek: <https://www.antratek.com/quectel>; Eltrox: <https://eltrox.pl/wireless-modules>.
[^3]: Symmetry Electronics distribuidor oficial Quectel US/EMEA: <https://www.semiconductorstore.com/cart/pc/Quectel-c5113.aspx>.

### Modelo backup 5G: Quectel RM510Q-GL

> Para test 5G en Lithuania/Vietnam donde 5G NSA esta desplegado
> en colos LIX/VNIX. Precio premium, tasa rotacion mas lenta
> (modem 5G + SIM 5G premium = mejor reputacion IP).

- Quectel RM510Q-GL (5G NR Sub-6 GHz). USD 220-280 unidad. MOQ 5.
- Solo recomendado para 10-20% del rack en Lithuania (5G premium
  para tier-1 high-payout cuentas Spotify Premium).

### Compra recomendada (50 unidades)

```
40x Quectel EG25-G       (Antratek EU, ~ EUR 1,720)
10x Quectel RM510Q-GL    (Symmetry Distrib, ~ USD 2,400) [solo Lithuania]
                                                  ----------
TOTAL MODEM 50 unidades inicial:        ~ 1,650 USD (sin 5G)
                                       o ~ 4,050 USD (con 10 5G en LT)
```

## 2. USB hubs powered + cables

### USB hub principal: StarTech ST7300UPB

- 7-port USB 3.0 powered hub, 12V/4A power adapter dedicado.
- Per-port power switch.
- 5 V / 900 mA por port garantizado (modems Quectel piden 500-700 mA bajo carga).
- Datasheet: <https://www.startech.com/en-us/cards-adapters/st7300upb>.
- Precio: USD 65-79 unidad (Amazon US, MOQ 1).
- Para 50 modems necesitas 50/7 ~ 8 hubs (con headroom 1 spare = 9).

### Alternativa economica: Anker A7515 (10-port USB 3.0)

- USD 90-110 unidad. 10 ports (mas eficiente density).
- Solo 5 hubs para 50 modems. Necesario adaptador de power suficiente
  (incluido).

### USB cables y extension activos

- USB extension activos USB 3.0 5m (PowerExtender o equivalente):
  USD 15-25 c/u, 6 unidades por rack para tendido del cabling
  desde servidor a hubs distribuidos en bandejas.

### Subtotal USB layer

```
9x StarTech ST7300UPB         (USD 70 c/u  = 630)
6x USB 3.0 active extension   (USD 18 c/u  = 108)
50x USB cable corto (modem - hub) (USD 1 c/u =  50)
                                                ----
                                  TOTAL USB:    788
```

## 3. SIM cards prepago

### Lithuania (rack #1)

- **Bite Mobile**, plan B2B "Internetas verslui": EUR 5/mes/SIM
  con 100 GB data, sin voz [^4].
- Activacion KYC via shell company UAB. Lead time 7-14 dias para
  contracts B2B con 50+ SIMs.
- 50 SIMs x EUR 5 x 3 meses = EUR 750 (~ USD 810).

[^4]: Bite Lithuania business plans: <https://www.bite.lt/verslui/internetas/internetas-modemui>.

### Bulgaria (rack #2)

- **A1 Bulgaria**, plan "Mobile Internet Business Lite": BGN 7/mes
  (~ EUR 3.58) con 30 GB data [^5].
- Activacion KYC via shell company OOD. Lead time 5-10 dias.
- Para 50 SIMs: EUR 179/mes; budget 3 meses iniciales = EUR 538
  (~ USD 580). NOTA: 30 GB es bajo para uso intensivo, reservar
  reload prepago adicional EUR 1-2/SIM/mes.

[^5]: A1 Bulgaria business mobile internet: <https://www.a1.bg/en/business/mobile-internet>.

### Vietnam (rack #3)

- **Viettel Telecom**, plan "Doanh Nghiep 4G Modem MIFI" prepago:
  VND 75,000/mes (~ USD 3) por 60 GB data [^6].
- Activacion KYC via shell company Cong Ty TNHH. Lead time 14-21
  dias.
- 50 SIMs x USD 3 x 3 meses = USD 450.

[^6]: Viettel business mobile data Vietnam: <https://vietteldoanhnghiep.vn/products/internet-4g>.

### Subtotal SIM (3 meses prepago, 50 SIMs por rack)

| Pais | 3 meses USD |
|------|-------------|
| Lithuania (Bite) | 810 |
| Bulgaria (A1) | 580 |
| Vietnam (Viettel) | 450 |

## 4. Servidor host

### Recomendado primario: Dell PowerEdge R730

- Specs target: 2x Xeon E5-2680v4, 256 GB DDR4 ECC, 4 TB NVMe (PCIe
  add-in card), 4x 1G NIC + 2x 10G NIC opcional.
- Compra usado refurbished: serverpartdeals.com, Bargain Hardware UK,
  Atlantic Recycling EU.
- Precio: USD 1,200-1,700 (configurado). Para colocation a 2U.

### Alternativa: Supermicro 6028U-TNRT+

- 2U platform, 24 DIMM slots (256 GB facil), 12 NVMe bays.
- Ideal para racks futuros con > 50 modems en mismo host.
- Precio: USD 1,800-2,500 refurbished.

### Hetzner Server Auction (alternativa colo Hetzner)

- Si la colocation es en Hetzner Falkenstein/Helsinki en lugar de
  proveedor local, alquiler dedicado AX102 con AMD Ryzen 9 7950X3D
  + 128 GB + NVMe: EUR 89-129/mes [^7].
- Caveat: Hetzner NO permite modems USB conectados a sus dedicated
  servers (los racks de Hetzner son de produccion estandar). Por
  eso la granja vive en colo de tercero, no en Hetzner. Hetzner
  sirve los workers + control plane, NO los modems.

[^7]: Hetzner Server Auction live: <https://www.hetzner.com/sb>.

### Decision recomendada por rack

```
Lithuania:  Dell R730 refurbished compra (~ USD 1,400)
Bulgaria:   Dell R730 refurbished compra (~ USD 1,400)
Vietnam:    Supermicro 5028D (1 socket, mas barato) (~ USD 800)
```

## 5. Networking

### Router

- **Mikrotik CCR2004-1G-12S+2XS** (12x 10G SFP+ + 2x 25G SFP28).
  Precio: USD 595-650.
- Soporte BGP, OSPF, VLAN tagging para segmentar trafico modems del
  trafico admin.
- WireGuard kernel module nativo desde RouterOS 7.x para mesh con
  control plane.

### Switch managed

- **Mikrotik CRS328-24P-4S+RM** (24x 1G PoE+ + 4x 10G SFP+). Precio:
  USD 410-450.
- PoE+ permite alimentar APs Wi-Fi de management opcional.
- VLAN-aware, recomendado para segmentar Subnet hubs USB del
  servidor host.

### Cables y accesorios

- UTP CAT6 cables x 30 (USD 75)
- Patchpanel 24 puertos rackeable (USD 45)
- Cable management arms (USD 35)
- Spare SFP+ DAC 10G x 4 (USD 60 total)

### Subtotal networking

```
Mikrotik CCR2004:        595
Mikrotik CRS328:         420
Cables + accesorios:     215
                         ----
Total network:           ~1,230 USD (overshoot del estimado de tabla, ajusta segun colo necesidades reales)
```

## 6. UPS y power

### UPS recomendado: APC Smart-UPS SRT 1500VA / 1000W

- Modelo: SRT1500RMXLI (RM 2U formato).
- Runtime a carga 60%: ~ 10-12 min (suficiente para shutdown
  ordenado del servidor host).
- Network management card AP9640 opcional (USD 240) para SNMP
  integration con Prometheus.
- Precio: USD 480-580 base + USD 240 NMC = USD 720-820.

### PDU rackeable

- Tripp Lite PDUMV15 (1U, 14 outlets, USD 110).
- Surge protection extra. Conexion a UPS principal.

### Spare batteries APC RBC93

- Para SRT1500: USD 130 spare set.

### Subtotal power

```
APC SRT1500 + NMC:        780
PDU Tripp Lite:           110
Spare battery RBC93:      130
                         ----
Total power:              1,020 USD
```

## 7. Estructura fisica del rack

> El proveedor colo provee los rails de rack 19" estandar; lo que
> el operador trae:

- Bandeja 1U para modems Quectel (custom mountar via velcro o
  tornilleria DIN-rail con adaptadores): USD 35 c/u, 4 unidades = 140.
- Bandeja 1U para hubs USB: 35 c/u, 2 unidades = 70.
- Cable management arms y velcro: 50.
- Etiquetas (Brother P-Touch o equivalente): 60.

Subtotal fisica: ~ 320 USD.

## 8. Setup colo (caution y 1er mes)

> Tipicamente el colo cobra:
> - Caution = 1 mes alquiler (refundable al cabo del contrato).
> - Setup fee = 0-200 EUR/USD por rack U.
> - 1er mes alquiler.

| Pais | Caution + setup + 1er mes |
|------|----------------------------|
| Lithuania (Bites Datacenter Vilnius, 2U budget) | EUR 350-450 (~ USD 380-490) |
| Bulgaria (Telepoint Sofia, 2U budget) | EUR 280-380 (~ USD 305-415) |
| Vietnam (FPT DC Hanoi, 2U budget) | USD 250-400 |

Estimado promedio: ~ USD 1,000.

## 9. Mano de obra setup

> Tecnico in-situ contratado para:
> - Recibir hardware (1 dia)
> - Cablear y montar (1.5 dias)
> - Verificar power-on, modem detection en host (0.5 dias)
> - Validar primer SMS recibido por hub (0.5 dias)

| Pais | Daily rate tecnico junior | 3 dias |
|------|---------------------------|--------|
| Lithuania | EUR 200-300/dia | EUR 750 (~ USD 810) |
| Bulgaria | EUR 120-180/dia | EUR 450 (~ USD 490) |
| Vietnam | USD 80-150/dia | USD 350 |

## Total CAPEX por rack — calculo final

```
Lithuania (incluye 10 modems 5G, premium hardware EU):
  Modems:         ~ 4,050
  USB:              788
  SIMs (3 meses):   810
  Server Dell:    1,400
  Network:        1,230
  Power:          1,020
  Fisica:           320
  Colo setup:       490
  Labor:            810
                 -------
                ~ 10,918 USD por rack 50 modems Lithuania (con 10 5G)

Bulgaria (4G only, hardware refurb):
  Modems:         ~ 1,400  (50 EG25-G economia escala)
  USB:              788
  SIMs (3m):        580
  Server:         1,400
  Network:        1,230
  Power:          1,020
  Fisica:           320
  Colo setup:       415
  Labor:            490
                 -------
                ~ 7,643 USD por rack 50 modems Bulgaria

Vietnam (4G only, server economico, labor barata):
  Modems:         ~ 1,400
  USB:              788
  SIMs (3m):        450
  Server Supermicro: 800
  Network:        1,230
  Power:          1,020
  Fisica:           320
  Colo setup:       400
  Labor:            350
                 -------
                ~ 6,758 USD por rack 50 modems Vietnam
```

> Estos numeros son top-down conservadores. En la practica con
> negociacion B2B en distribuidores y compra usada, salen 15-25%
> mas baratos. Reservar buffer 10% para incidencias (modems DOA,
> cables defectuosos, hubs que mueren).

## Tabla de procurement / lead times resumen

| Item | Lead time | Comprar en |
|------|------------|------------|
| Modems Quectel EG25-G (40+) | 5-30 dias | Antratek EU / Symmetry US |
| Modems Quectel 5G RM510Q-GL | 21-45 dias | Symmetry US o Quectel direct |
| USB hubs StarTech | 5-14 dias | Amazon US, B2B re-seller |
| Server Dell R730 refurb | 5-10 dias | serverpartdeals, Bargain Hardware |
| Mikrotik CCR2004 + CRS328 | 14-30 dias | Mikrotik distributor local (LMnet en LT, etc.) |
| APC SRT1500 + NMC | 7-14 dias | Distribuidor APC autorizado (Schneider Electric local) |
| SIM cards B2B contract | 7-21 dias | Bite (LT), A1 (BG), Viettel (VN) - via shell company |
| Colo contratado | 14-30 dias firma + setup | Vease colo-providers.md |

## Politica de spares

Mantener spare per rack:

- 5x modems Quectel adicionales (10% spare ratio, para reemplazos
  de DOA o flagged > 5).
- 1x USB hub StarTech adicional.
- 1x UPS battery set (RBC93).
- 50x SIMs spare per pais (10% del rack, para rotacion fisica).

Subtotal spare por rack: ~ USD 600.
