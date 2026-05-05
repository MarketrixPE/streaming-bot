# 01 — Tesis de producto

## ICP (Ideal Customer Profile)

**Cliente objetivo**: operador de catalogo propio (no reseller SMM, no agencia growth), volumen 50k-2M streams/mes, con dolor especifico en la capa de ejecucion stealth.

### Caracteristicas concretas

| Dimension | Valor objetivo |
|---|---|
| Tipo | Operador grey/black con catalogo propio (artistas tokens, lo-fi, sleep, niche) |
| Volumen mensual | 50k - 2M streams/mes generados |
| Stack actual | Selenium plain o Playwright vanilla, fingerprints estaticos comprados, sin behavioral engine |
| Dolor primario | Bans cluster (ratio bans > 5%/semana), incapacidad para escalar sin perder cuentas, no tienen ML behavioral |
| CAPEX disponible | $5k - $50k/mes |
| Tecnico | Tiene devs in-house (no agencias 100% no-tech) |
| Geo | LATAM, EU del Este, MENA, SE Asia (no objetivos en US/UK por exposure legal) |

### Anti-ICP (a quien rechazamos)

- Resellers SMM puros que solo revenden volumen prefab (no tienen catalogo, no son nuestro cliente).
- Agencias whitehat de marketing musical (no necesitan stealth, son competidoras de servicios distintos, evitar).
- Operadores que requieren cuentas / proxies (no hay producto para ellos en este SaaS).
- Clientes solicitando SLA contractual o KYC formal pesado (incompatible con setup OPSEC).
- Clientes solicitando facturacion fiat con identidad real (incompatible con compartmentalizacion).

## Producto SaaS — propuesta de valor concreta

Tres capas de capacidad expuestas como API + SDK:

### Capa 1: Stealth Browser Sessions

- API: `POST /v1/sessions`.
- Devuelve un endpoint websocket o un puppeteer-protocol over WSS hacia un browser remoto managed.
- El browser corre en granja propia (modems 4G/5G + colocacion bare-metal) con:
  - Patchright/Camoufox mix 70/30 al ultimo upstream.
  - Fingerprint coherente (UA correlacionado a OS/locale/JA4/HTTP2/Client Hints).
  - Proxy seleccionable (cliente trae el suyo o usa el nuestro, marcado en pricing distinto).
  - Persistencia de cookie jar / localStorage / sessionStorage por cliente (encriptado at rest).
- Pricing: **$0.05 por sesion abierta y cerrada exitosamente**, prorateado por minuto si > 30 min.

### Capa 2: Behavioral Playback (Rich Sessions)

- API: `POST /v1/behaviors/play_session`.
- Cliente provee URL de target (track / playlist / artista) y elige un `behavior_profile_id`.
- El motor ejecuta una sesion completa con: navegacion humana, ghost-cursor patterns, save/skip/queue ratios coherentes con el profile, decision delays modulados por LLM-style stochastic, scroll inertia.
- Profiles disponibles: `superfan_premium`, `casual_premium`, `discovery_free`, `super_fan_free` y variantes geo (US, BR, IN, etc).
- Pricing: **$0.20 por sesion**, incluye sesion stealth + comportamiento.

### Capa 3: Profile Catalog (gratuito, parte del SDK)

- API: `GET /v1/profiles`.
- Lista profiles disponibles, descripcion textual, parametros que acepta (geo, premium_tier, intensity).
- No genera revenue directo, es producto de descubrimiento.

## Defensibilidad — por que es dificil replicar

| Capa | Como un nuevo entrante intentaria copiarla | Por que no le sale |
|---|---|---|
| Codigo motor stealth | Open-source los componentes (Patchright, Camoufox, ghost-cursor) | Integracion estable + parche continuo de breakages requiere 6-9 meses + corpus de fallos |
| Coherent Fingerprint Engine | Comprar browserforge fingerprints | Solo el pool no basta. Coherencia JA4/HTTP2/UA/Client-Hints/locale/timezone es el moat |
| Behavioral profiles | Definir manualmente | Un profile manual sobrevive 4-6 semanas hasta que antifraud lo detecta. Los nuestros se entrenan sobre **20M+ sesiones reales acumuladas Año 1-2** |
| Granja 4G/5G | Setup propio | CAPEX 50-150k + 6-12 meses + relacion operativa con SIM providers en Lithuania/Bulgaria/Vietnam |
| Multi-tenancy aislada | Build infra | Diseñar correctamente RLS Postgres + isolation cuentas/proxies por tenant es mas dificil que parece |

**El moat real es el corpus behavioral**. Cada cliente nuevo aporta sesiones (de manera anonima y agregada, sin info identificadora cross-tenant) que mejoran los profiles. Esto es un network effect interno: mas tenants -> mas data -> mejores profiles -> mejor retencion.

## Por que NO competimos con nosotros mismos

Modelo competitivo claro:

```
Nuestro propio operador interno (Año 1-2):
  catalogo_propio + cuentas_propias + proxies_propios + motor_propio
  -> royalties

Cliente SaaS (Año 3):
  catalogo_propio_cliente + cuentas_propias_cliente + proxies_propios_cliente + MOTOR_NUESTRO
  -> royalties_cliente

Lo que vendemos: SOLO motor.
Lo que NO vendemos: catalogo, cuentas, proxies.
```

Las decisiones competitivas reales (que catalogo producir, en que nicho, en que geo, con que distribucion) las toma cada operador con sus propios datos. Nosotros vendemos la pala, no la mina.

Si un cliente decide producir musica en el mismo nicho que nosotros: legitimamente compite con nosotros como cualquier otro operador. Su ventaja por usar nuestro motor es marginal (mejor ratio sesion-exitosa) — y es la misma ventaja que nuestro propio operador interno tiene. Net impacto: el mercado se vuelve mas eficiente, sale share de operadores incompetentes y nuestro propio operador y nuestros clientes ganan share contra esos.

## Pricing — racional cuantitativo

### Costo marginal real por sesion

| Concepto | Costo/sesion basica | Costo/sesion rich |
|---|---|---|
| Compute (Hetzner share) | $0.004 | $0.008 |
| Mobile slot (granja 4G amortizado) | $0.012 | $0.025 |
| Fingerprint pool / browserforge subscription | $0.001 | $0.001 |
| Captcha solve estimado | $0.003 | $0.007 |
| Bandwidth | $0.001 | $0.003 |
| Mantenimiento, parches, ML retrain | $0.005 | $0.010 |
| **Total costo marginal** | **$0.026** | **$0.054** |

### Pricing al cliente

- Sesion basica: **$0.05** (margen bruto 48%)
- Sesion rich: **$0.20** (margen bruto 73%)

### Por que estos numeros funcionan

- Operador medio (50k-2M streams/mes) usa `streams_mes = sessions_mes` aproximadamente (1 stream/sesion en average — sesion ejecuta 3-5 plays pero sesiones largas se cobran como 1).
- Costo motor para cliente: $2.5k - $100k/mes en regimen.
- Comparativa cliente: armarse el motor solo cuesta $50-150k CAPEX inicial + $15-30k/mes OPEX. Nuestro pricing rompe el make-vs-buy en favor de buy para tenants < $200k MRR.

## Hipotesis verificables

| Codigo | Hipotesis | Validacion |
|---|---|---|
| HT1 | Existe demanda real de >= 50 tenants Mes 12 al pricing actual | Pilots Q1 -> Q3 + tracking conversion DM/referral |
| HT2 | Detection rate cliente <= 1.2x detection rate operador interno | Comparar bans/sessions entre tenants y operador interno |
| HT3 | Corpus behavioral acumulado mejora profile retention >= 5%/mes vs profile estatico | A/B test cohort tenants nuevos sobre profile v_actual vs profile_estatico_baseline |
| HT4 | Operadores no piden datos cross-tenant (no usan SaaS para spying) | Auditoria logs API por tenant |
| HT5 | Margen bruto sostiene >= 65% incluso con incremental utility costs | Tracking unit economics mensual |

## No-objetivos del producto

- NO multi-region failover automatic durante Año 3 (single region inicial Hetzner FI/DE).
- NO compliance certificaciones (SOC2, GDPR formal). Compromiso minimo legal en TOS.
- NO white-label / reskinning para integradores Año 3.
- NO panel admin web para tenant Año 3 (todo via API + Telegram bot para ack billing).
