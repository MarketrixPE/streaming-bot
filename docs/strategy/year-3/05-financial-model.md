# 05 — Modelo financiero del spinoff

## Asunciones base

| Asuncion | Valor | Notas |
|---|---|---|
| Tenants Mes 12 Año 3 | 50 | Mix: 30 Standard, 15 Pro, 5 Volume |
| Sesiones/dia/tenant promedio | 1,000 | Mediana, Standard ~500, Volume ~5k |
| Sesiones/mes total | 1,500,000 | 50 * 1k * 30 |
| Mix sesiones basicas vs rich | 50% / 50% | Conservador. Ratio realista probable 40/60 favoreciendo rich |
| Pricing basica | $0.05 | sesion exitosa |
| Pricing rich | $0.20 | sesion exitosa |
| Tasa de exito | 95% basica, 90% rich | Sesiones fallidas no se cobran |
| ARPU mensual promedio | $3,750 | revenue/tenant Mes 12 |
| Crecimiento tenants Q1->Q4 | 5 -> 15 -> 35 -> 50 | Basado en pilots Q1, expansion Q2-Q4 |

## Revenue model — Mes 12 Año 3 (regimen target)

### Calculo bottom-up

```
Sesiones/mes total            = 1,500,000
Sesiones/mes basicas (50%)    =   750,000
Sesiones/mes rich (50%)       =   750,000

Sesiones cobradas basicas     =   750,000 * 0.95 = 712,500
Sesiones cobradas rich        =   750,000 * 0.90 = 675,000

Revenue basicas/mes           = 712,500 * $0.05 = $35,625
Revenue rich/mes              = 675,000 * $0.20 = $135,000
Revenue subscription tier Pro = 15 * $99       = $1,485
Revenue subscription Volume   = 5  * $0       = $0 (incluido en negociacion)

Revenue mes 12 spinoff        ~ $172,000

Add-ons / overage / ad-hoc    ~ $15,000 (estimado conservador)

Revenue total Mes 12 spinoff  ~ $187,000
```

ARPU = $187k / 50 = $3,740/tenant/mes.

## Curva de revenue — Año 3 mes a mes

| Mes | Tenants | Sessions/dia/tenant | Sessions/mes total | Revenue mensual estimado |
|---|---|---|---|---|
| 1 | 5 (pilot) | 200 | 30,000 | $4,500 |
| 2 | 5 | 400 | 60,000 | $9,000 |
| 3 | 8 | 600 | 144,000 | $21,600 |
| 4 | 12 | 700 | 252,000 | $37,800 |
| 5 | 15 | 800 | 360,000 | $54,000 |
| 6 | 20 | 800 | 480,000 | $72,000 |
| 7 | 25 | 850 | 637,500 | $95,625 |
| 8 | 30 | 900 | 810,000 | $121,500 |
| 9 | 35 | 900 | 945,000 | $141,750 |
| 10 | 40 | 950 | 1,140,000 | $171,000 |
| 11 | 45 | 950 | 1,282,500 | $192,375 |
| 12 | 50 | 1,000 | 1,500,000 | $225,000 |

(El revenue mensual usa pricing blended $0.15 promedio sesion para simplificar; el calculo bottom-up de Mes 12 anterior es la fuente de verdad).

## Costos

### CAPEX inicial Año 3 (Q1-Q2)

| Item | Costo |
|---|---|
| Setup legal entidad spinoff (BVI + RAK) | $15,000 |
| Brand desarrollado (logo, dominio, brand book minimal) | $4,000 |
| Dev sprint inicial: API + SDK Python + SDK TS + multi-tenancy | $30,000 (3 meses contractor + lead) |
| Setup BTCPay self-hosted + integracion billing | $5,000 |
| KYC tooling (AML check API integration) | $4,000 |
| Migration / segregation infra (nodes Hetzner + WireGuard mesh) | $7,000 |
| Buffer documentacion + runbooks + tests integration | $8,000 |
| Buffer contigencia | $7,000 |
| **Total CAPEX inicial** | **$80,000** |

### OPEX mensual Año 3 (Mes 6 onwards regimen)

| Item | Costo mensual |
|---|---|
| Hetzner spinoff dedicated nodes + edge | $1,500 |
| Cloudflare + DNS + monitoring | $500 |
| BTCPay VPS + reconciliation | $100 |
| Granja overhead incremental (30% sobre operador interno share) | $4,500 |
| Captcha solver budget (CapSolver tenant-attributed) | $1,200 |
| Soporte / community manager (Q3+ 2 personas) | $4,500 |
| ML retrain + behavioral ETL compute | $400 |
| Legal retainer + compliance ad-hoc | $1,500 |
| Banking / cripto on-ramp fees + AML services | $400 |
| Buffer / inventarios / herramientas | $400 |
| **Total OPEX mensual regimen** | **$15,000** |

### OPEX fase early (Mes 1-5) — reducido

- Mes 1-2: $5k/mes (sin soporte dedicado, founder time covered, infra inicial).
- Mes 3-4: $8k/mes.
- Mes 5: $12k/mes.

## Estado financiero Año 3 spinoff

### P&L mensual proyectado

| Mes | Revenue | OPEX | Margen bruto | Cumulative cashflow (vs CAPEX -$80k) |
|---|---|---|---|---|
| 1 | $4,500 | $5,000 | -$500 | -$80,500 |
| 2 | $9,000 | $5,000 | $4,000 | -$76,500 |
| 3 | $21,600 | $8,000 | $13,600 | -$62,900 |
| 4 | $37,800 | $8,000 | $29,800 | -$33,100 |
| 5 | $54,000 | $12,000 | $42,000 | $8,900 |
| 6 | $72,000 | $15,000 | $57,000 | $65,900 |
| 7 | $95,625 | $15,000 | $80,625 | $146,525 |
| 8 | $121,500 | $15,000 | $106,500 | $253,025 |
| 9 | $141,750 | $15,000 | $126,750 | $379,775 |
| 10 | $171,000 | $15,000 | $156,000 | $535,775 |
| 11 | $192,375 | $15,000 | $177,375 | $713,150 |
| 12 | $225,000 | $15,000 | $210,000 | $923,150 |

### Break-even

- **Mes 5**: cumulative cashflow > 0 ($8.9k positivo).
- Tras break-even la curva es exponencial por leverage de granja existente (incremental cost por sesion adicional es bajo: $0.026 basica / $0.054 rich, con pricing cliente $0.05 / $0.20 = margen bruto unitario 48%/73%).

### Margen bruto progresion

| Mes | Margen bruto % revenue |
|---|---|
| 1 | -11% |
| 3 | 63% |
| 6 | 79% |
| 12 | 93% |

(Margen bruto = revenue - OPEX directamente atribuible a sesiones. Excluye CAPEX amortizado).

## Sensibilidad — escenarios

### Escenario pesimista (50% de target)

- 25 tenants Mes 12.
- Sessions/dia/tenant: 600.
- Sessions/mes total: 450,000.
- Revenue Mes 12: ~$67,500/mes.
- Break-even: Mes 9-10.
- Cumulative Mes 12: ~$200k positivo.

### Escenario base (target documento)

- 50 tenants Mes 12.
- Sessions/mes total: 1.5M.
- Revenue Mes 12: ~$225k/mes.
- Break-even: Mes 5.
- Cumulative Mes 12: ~$923k positivo.

### Escenario optimista (130% target)

- 65 tenants Mes 12.
- Sessions/dia/tenant: 1,200.
- Sessions/mes total: 2.34M.
- Mix favoreciendo rich (60%/40%).
- Revenue Mes 12: ~$370k/mes.
- Break-even: Mes 4.
- Cumulative Mes 12: ~$1.5M positivo.

## CAC / LTV

### CAC

- Canales 1-2 (referrals + foros DM): CAC ~ $200-500/tenant (tiempo founder + descuento pilot 50% primer mes).
- Canal 3 (word-of-mouth): CAC ~ $50/tenant (programa referral 5%).
- CAC blended Mes 12: ~$300/tenant.

### LTV

- ARPU mensual: $3,740.
- Margen bruto unitario blended: 65%.
- Churn mensual asumido: 8%.
- Lifetime esperado: 1/0.08 = 12.5 meses.
- LTV = 3,740 * 0.65 * 12.5 = **$30,388**.
- LTV/CAC = ~100x. Robusto incluso en escenarios pesimistas.

## Riesgos financieros

| Riesgo | Impacto | Mitigacion |
|---|---|---|
| Concentracion top-3 tenants > 35% revenue | Caida ingreso 30%+ si pierde uno | Cap voluntario + diversificacion activa |
| Banked cripto regulatorio change | Refunds o bloqueos | 80% cold storage offshore, 2 wallets backup |
| Costo modems incrementa 50% | OPEX +$2k/mes | Pre-purchase de SIMs 6 meses, contratos largos |
| AML alerta sobre wallet | Banking off-ramp bloqueado | Multi-exchange off-ramp + reservas USDT cold |
| Pricing erosion competencia (un competidor copia) | Margen bruto -10pp | Defensa via behavioral profile depth (corpus) |

## Reinversion vs distribucion

Politica recomendada Año 3:

- 60% cashflow reinvertido en infra (granja, devs, profile depth).
- 30% cashflow a holding offshore (Estonia OU / BVI personal layer).
- 10% buffer reservas operativas (3 meses runway).

A partir de cumulative cashflow > $1M, abrir distribucion a estructura final.
