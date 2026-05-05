# Comparativa proveedores colo — Lithuania / Bulgaria / Vietnam

> Decision documentada Mes 7-9 (`farm-scale`). Revisar cada 12
> meses para actualizar precios. Precios verificados Q1 2026, con
> fuentes; negociar siempre B2B antes de firmar.

## Criterios de decision

Por orden de peso operativo:

1. **Cobertura 4G/5G en el barrio del DC**: el modem 4G/5G NO es
   un proxy backbone, depende de la torre celular fisica. Si el
   DC esta en industrial estate sin coverage de varios operadores,
   IP rotation es pobre = anti-fraud signal negativa.
2. **Costo /U /mes incluyendo bandwidth**: target <= EUR/USD 80/U
   incluyendo 1 Gbps simetrico.
3. **Latencia uplink hasta Frankfurt (DE-CIX) y Helsinki (FNNIX)**:
   <= 30 ms si el rack reportara metrics al control plane Hetzner.
4. **Energia incluida y sustainability**: target <= EUR/USD 0.18/kWh
   (kWh consumido directo).
5. **Regulacion local de telecoms**: KYC SIM B2B viable, sin retencion
   masiva de contratos.
6. **Acceso fisico hands & remote**: 24/7 acceso para tecnico, no
   appointment booking restrictivo.
7. **Estabilidad politica + risk reputational**: no jurisdicciones
   inestables o bajo sanciones recientes.

---

## LITHUANIA

### Bites Datacenter Vilnius (BiTe)

- Direccion: Saltoniskiu 7, Vilnius. <https://www.bite.lt/duomenu-centras>.
- Operador: BiTe Lietuva (parent: Provident Equity Partners).
- Tipo: Tier 3 carrier-neutral, 2 salas, ~ 2,500 m2.
- Coverage 4G/5G en barrio: BiTe propio + Telia LT + Tele2 LT, 5G
  NSA en banda 3500 MHz (Telia + Tele2).
- Connectividad: LIX peering, conexion directa a DE-CIX Frankfurt
  (~ 25 ms latencia).
- Energia: PUE ~ 1.4 declarado, energia 100% verde (Lithuania mix
  hidro + nuclear).
- Tarifas (Q1 2026):
  - Half-rack (22U): EUR 350-450/mes.
  - Full rack (42U): EUR 600-750/mes.
  - 2U budget: EUR 75-95/mes (incluyendo 100 Mbps simetrico).
  - Bandwidth premium 1 Gbps simetrico add-on: EUR 60-90/mes.
  - Power 5A 230V incluido en pricing 2U; extra 5A: EUR 35/mes.
- KYC para 50 SIMs B2B con BiTe: 7-14 dias, contract en lituano +
  ingles. Activacion masiva via Bite Verslui portal.
- Setup fee: EUR 200 una vez.
- Acceso fisico: 24/7 con biometric + escort opcional EUR 30/h.

### Telia Lithuania DC (alternativa)

- Vilnius, Antakalnio 22. <https://www.telia.lt/duomenu-centras>.
- Tier 3, mas pequeno.
- 2U budget: EUR 80-105/mes.
- Coverage similar pero mas dependiente de Telia red propia
  (menos diversidad).
- Recomendado SOLO si Bites Datacenter rechaza el contract.

### Recomendacion Lithuania

```
Proveedor:        Bites Datacenter Vilnius
Plan:             2U + 1 Gbps simetrico + 5A power adicional
Costo /mes:       EUR 75 + 90 + 35 = EUR 200/mes (~ USD 218)
Costo /modem/dia: EUR 200 / (50 modems * 30 dias) = EUR 0.13 (~ USD 0.14)
KYC SIM:          BiTe Verslui, EUR 5/mes/SIM 100 GB (ver hardware-bom.md)
Latencia FRA:     ~ 25 ms a DE-CIX Frankfurt
Latencia HEL:     ~ 35 ms a Helsinki (Hetzner data plane)
Setup fee:        EUR 200 (una vez)
```

---

## BULGARIA

### Telepoint Sofia

- Direccion: Asparuhov 67, Sofia. <https://www.telepoint.bg>.
- Operador: Telepoint, mayor carrier-neutral DC EE.
- Tipo: Tier 3+, 5,500 m2.
- Coverage 4G/5G: A1 BG + Vivacom + Yettel, 5G NSA banda 3500 MHz
  desplegado en Sofia centro 2024-2025.
- Connectividad: BIX.bg peering primario, link directo Frankfurt
  via SEEUR fiber (~ 35 ms).
- Energia: PUE 1.4, mix energia BG (nuclear Kozloduy + termica).
  Costo electricidad BG es de los mas bajos UE (EUR 0.12-0.15/kWh
  industrial 2026).
- Tarifas (Q1 2026):
  - 2U budget: EUR 65-85/mes (incluyendo 100 Mbps).
  - 1 Gbps simetrico add-on: EUR 50-75/mes.
  - Half-rack: EUR 280-380/mes.
  - Power 5A: incluido base; extra 5A: EUR 25/mes.
- Setup fee: EUR 100 una vez.
- Acceso fisico: 24/7 con NDA + biometrico.

### A1 Bulgaria DC (alternativa, mas caro)

- Direccion: Tsarigradsko Shose 115, Sofia.
- Carrier (no neutral). Costo /U: EUR 95-130/mes 2U.
- Solo recomendable si Telepoint capacity full o KYC dificultoso.

### Recomendacion Bulgaria

```
Proveedor:        Telepoint Sofia
Plan:             2U + 1 Gbps simetrico
Costo /mes:       EUR 75 + 60 + 25 = EUR 160/mes (~ USD 174)
Costo /modem/dia: EUR 160 / (50 modems * 30 dias) = EUR 0.107 (~ USD 0.116)
KYC SIM:          A1 Business Mobile Internet, BGN 7/mes (~ EUR 3.6) 30 GB
Latencia FRA:     ~ 35 ms a DE-CIX Frankfurt
Latencia HEL:     ~ 45 ms a Helsinki
Setup fee:        EUR 100 (una vez)
```

---

## VIETNAM

### FPT Telecom DC Hanoi (FPT DC1)

- Direccion: Cau Giay, Hanoi. <https://fptcloud.com>.
- Operador: FPT Telecom (top 3 ISP VN).
- Tipo: Tier 3, ~ 11,000 m2.
- Coverage 4G/5G: Viettel + Vinaphone + MobiFone; Viettel 5G NSA
  desplegado en Hanoi/HCMC/Da Nang 2024.
- Connectividad: VNIX peering nacional + cable submarino AAG/SMW3
  para internacional (latencia premium pero alto cost variable).
- Energia: PUE 1.5, electricidad VN (predominantemente termica
  carbon, EUR 0.10-0.13/kWh industrial).
- Tarifas (Q1 2026):
  - 2U budget: USD 150-200/mes (incluyendo 200 Mbps internacional + 1 Gbps domestico).
  - 1 Gbps internacional simetrico premium: USD 200-350/mes.
  - Half-rack: USD 600-800/mes.
- Setup fee: USD 300 una vez.
- Acceso fisico: 24/7 con appointment booking 4h notice (no walk-in).
- KYC para 50 SIMs B2B con Viettel: 14-21 dias, contract en
  vietnamita (necesita traduccion certificada local).

### Viettel IDC Hanoi (alternativa, operador-incumbente)

- Direccion: Pham Hung, Hanoi. <https://idc.viettel.com.vn>.
- Costo: USD 130-180/mes 2U.
- Caveat: Viettel es state-affiliated, KYC mas estricto, peer
  con bandwidth controls del state. Recomendable SOLO si la
  shell company VN ya tiene historial 1+ ano operativo.

### Recomendacion Vietnam

```
Proveedor:        FPT Telecom DC Hanoi (FPT DC1)
Plan:             2U + 200 Mbps internacional + 1 Gbps domestico
Costo /mes:       USD 175 (incluido en 2U budget)
                  Si necesitas 1 Gbps internacional: + USD 200 = USD 375/mes
Costo /modem/dia: USD 175 / (50 modems * 30 dias) = USD 0.117
                  (USD 375 / (50 * 30) = USD 0.250 con 1 Gbps internacional)
KYC SIM:          Viettel Doanh Nghiep, VND 75,000/mes (~ USD 3) 60 GB
Latencia FRA:     ~ 220 ms (alto, expected via cable submarino)
Latencia HEL:     ~ 230 ms
Setup fee:        USD 300 (una vez)
```

> NOTA Vietnam: la latencia internacional alta NO es un problema
> para los modems serving cuentas DSP que estan localizadas en
> Asia (ID, PH, VN, IN). Si los workers tambien estan en Asia
> (recomendable: nodo workers en Singapore o HK), no afecta. Si
> los workers estan en Hetzner Helsinki, hay que acomodar 230 ms
> RTT para los control commands; en general aceptable.

---

## Comparativa final con criterios

| Criterio | Lithuania (BiTe) | Bulgaria (Telepoint) | Vietnam (FPT DC1) |
|----------|------------------|------------------------|---------------------|
| Costo /modem/dia (colo only) | EUR 0.13 | EUR 0.107 | USD 0.117 |
| Costo /SIM/mes | EUR 5 | EUR 3.58 | USD 3 |
| Coverage 4G | Excelente (3 ops) | Muy bueno (3 ops) | Bueno (3 ops, Viettel dominante) |
| Coverage 5G en area | Si (Telia, Tele2) | Si (A1, Vivacom) | Si (Viettel, Vinaphone) |
| Latencia DE-CIX FRA | 25 ms | 35 ms | 220 ms |
| Energia EUR/kWh | 0.18-0.22 | 0.12-0.15 | 0.10-0.13 |
| KYC SIM B2B viable | Si, 7-14d | Si, 5-10d | Si, 14-21d (necesita traduccion) |
| Acceso fisico 24/7 | Si | Si | Appointment 4h notice |
| Reputacional EU AMLD | Bajo (UE plena) | Bajo (UE plena) | Mediano (lista FATF observada periodicamente) |
| Restriccion telecom local | Ninguna | Ninguna | Bandwidth controls + DPI activo |
| Recomendacion roll-out | Mes 7 (rack #1, anchor) | Mes 8 (rack #2, replicar setup) | Mes 9 (rack #3, validar Asia) |

## OPEX recurrente combinado (post-Mes 9, 3 racks 50 modems c/u)

```
Lithuania colo:     EUR 200/mes  (~ USD 218)
Bulgaria colo:      EUR 160/mes  (~ USD 174)
Vietnam colo:       USD 175/mes
                                 ----------
Subtotal colo:                   ~ USD 567/mes

Lithuania SIMs (50): EUR 250/mes (~ USD 272)
Bulgaria SIMs (50):  EUR 179/mes (~ USD 195)
Vietnam SIMs (50):   USD 150/mes
                                 ----------
Subtotal SIMs:                   ~ USD 617/mes

TOTAL infra colo + SIMs (150 modems): ~ USD 1,184/mes
Por modem por dia: USD 0.263

Anadir: bandwidth overage (raro), spare hands & eyes, electricidad
adicional, overhead = ~ + USD 150-300/mes.

Costo all-in granja 150 modems: USD 1,500-1,800/mes.
Costo /modem/dia all-in (sin amortizar hardware ni labor):
  USD 0.33-0.40 / modem / dia.

Anadir amortizacion hardware (~ USD 25k/3 anos = USD 0.15/modem/dia)
+ labor mantenimiento (USD 0.50/modem/dia):
  TARGET FINAL: USD 1.50-2.50 / modem / dia all-in.
```

## Decision matrix por escenario

| Escenario | Recomendacion |
|-----------|---------------|
| Solo 1 rack inicial Mes 1-7 | Lithuania (Bites Datacenter): KYC mas rapido, EU compliance, latencia Frankfurt minima |
| Expansion Mes 8 (2 racks) | + Bulgaria (Telepoint): costo mas bajo, geo diversidad EU |
| Expansion Mes 9 (3 racks) | + Vietnam (FPT): geo Asia, payout DSP Asian markets |
| Expansion Mes 10+ (4 racks) | + Indonesia (DCI Jakarta) o + Czech Rep (DataSpring Praga) o + Mexico (KIO Networks DF) - dependiente de la geo del catalogo objetivo |

## Procedimiento contratacion colo

1. Mandar RFP simplificado: "Operacion: data analytics; 2U budget;
   100 Mbps minimo; necesidad acceso 24/7 hands-on; contract 12
   meses". NO mencionar "modems" ni "telecoms" en el RFP inicial.
2. Verifica via call/visita que los racks vecinos NO sean operadores
   visiblemente competidores o suspect (otros bot operators usando
   el mismo DC pueden compartir IP cluster signal).
3. Contract minimo: 12 meses con clausula salida 30 dias notice
   despues de mes 6 sin penalty.
4. Negociar: setup fee waived al firmar 12 meses; primer mes free
   o 50% off es estandar en colos LT/BG; en VN es mas raro.
5. Firma via shell company local. Pago primer mes via cuenta local
   shell, NO via cripto ni cuenta del holding patrimonial.

## Reglas DURAS de operacion

1. NUNCA dar acceso fisico al rack a personas no incluidas en el
   nominee director / contract employee de la shell local.
2. NUNCA dejar el switch / router con WebFig habilitado por defecto:
   acceso solo via WireGuard del control plane, mgmt subnet
   firewalled.
3. NUNCA usar el mismo IP block del colo como source IP para
   conexiones outbound al control plane Hetzner; usar WireGuard
   tunnel siempre.
4. NUNCA conectar laptop personal del operador al management VLAN
   del rack para troubleshooting; usar laptop dedicada sin mac
   address registrada en sitios personales.
