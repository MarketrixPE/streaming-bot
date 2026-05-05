# 03 — Go-to-market

## Principio rector

Distribucion **discreta, dirigida y prepago cripto**. NO presencia publica (ni LinkedIn, ni Twitter, ni website indexable salvo landing minima behind-cookie). El cliente nos encuentra a traves de canales del mercado gris donde ya esta.

## Canales de distribucion

### Canal 1 — Referrals operadores conocidos

Operadores con los que la red interna del founder ya ha tratado en Año 1-2 (sin haber vendido nada). Aproximacion: DM directo en Telegram / Signal / XMPP, oferta pilot privado con descuento 50% primer mes.

Capacidad estimada: 8-15 operadores en Año 3, conversion 40-60%.

### Canal 2 — Foros y comunidades grises

- BlackHatWorld DM (no posts publicos en hilos: contraproducente para nuestra OPSEC).
- Discord gated comunidades de operadores (entrada por invitacion).
- Telegram channels privados (un par identificados, ninguno publico para no exponer brand).

Capacidad estimada: 20-40 leads/mes Q3 Año 3 con 5-15% conversion.

### Canal 3 — Word-of-mouth pilots

Tras 3-5 pilots exitosos, los propios clientes recomiendan. Es el canal de mayor conversion (60%+) pero requiere base initial.

### Canal 4 (opcional) — Listado en marketplaces grises

Plataformas como AccsMarket / similares NO listan infrastructure SaaS aun, pero existe oportunidad de listing no-publico bajo brand-stealth si volumen lo justifica Q4 Año 3.

## Pricing model — comercial

### Prepago credits

- Cliente compra credits via cripto (USDT/USDC en TRC20 / ERC20 / SOL).
- Minimo recarga inicial: $500.
- Top-ups: $100 minimo.
- No refund post-uso. Refund parcial unicamente si downtime nuestro > 6h consecutivas (raro).

### Tiers operativos

| Tier | Spend mensual | Beneficios |
|---|---|---|
| Standard | $0 - $5k | Pricing publico, soporte Telegram con SLA best-effort |
| Pro | $5k - $25k | -10% sobre rich sessions, dashboard Grafana acceso, soporte priorizado |
| Volume | $25k+ | Negociacion individual, profile customizado posible, infra dedicada (modems compartidos solo con otros volume) |

### KYC ligero

- Email de contacto (puede ser ProtonMail / Tutanota).
- Wallet cripto desde la que se cobra.
- Nota de uso libre (`"automated testing for music apps"` por defecto, no se valida).

NO pedimos: pasaporte, business registration, identidad real, origen de fondos.

## Pilot Q1 Año 3 — primeros 5 operadores

### Criterios de seleccion

- Volumen 500k+ streams/mes (suficiente para ser relevante en feedback).
- Tech stack ya con devs (puede integrar SDK).
- Ningun reporte de actividad escandalosa (acoso de comunidades de artistas, doxxing, etc).
- Compromiso de feedback semanal durante 8 semanas pilot.

### Oferta pilot

- 50% descuento primer mes ($1.5k credit gratis si recarga $3k).
- Acceso directo a CTO via Telegram.
- Posibilidad de profile customizado para su nicho.
- Compromiso de NO pedir testimonio publico (incompatible con OPSEC mutua).

### Metricas de exito pilot (semanas 1-8)

| Metrica | Target |
|---|---|
| Sesion exitosa rate | >= 90% |
| Bans cliente vs baseline cliente Año 1-2 | -30% |
| Tickets soporte | <= 5/semana per pilot |
| Renovacion mes 2 | 4 de 5 |
| NPS interno (informal Telegram poll) | >= 7/10 |

## Q2-Q4 expansion plan

### Q2 (mes 4-6 Año 3) — 15 tenants

- Procesar 10-15 leads adicionales del canal 2.
- Mejorar onboarding: docs publicos behind-cookie, video walkthrough en Loom (no YouTube).
- Establecer Telegram channel privado para community (announcements + status incidents).

### Q3 (mes 7-9) — 35 tenants

- Lanzar SDK Python + TypeScript publicamente en pypi/npm (con docs, sin marketing publico).
- Programa referral: tenant que trae cliente nuevo recibe 5% del primer mes facturado del nuevo.
- Iniciar profile customizado a tier Volume (revenue sticky).

### Q4 (mes 10-12) — 50 tenants

- Establecer billing automatizado completo via cripto-on-ramp (BTCPay self-hosted).
- Activar webhook deliveries con dead-letter queue persistente.
- Crear runbook compliance interno para auditoria propia.

## Onboarding flow

```
0. Lead llega via DM o referral
1. NDA-lite (TOS + 1 pagina) firmada electronicamente
2. Wallet whitelisted; primer top-up $500 minimo via USDT
3. API key generada, enviada por Telegram cifrado
4. Cliente integra SDK (docs.[brand-spinoff].io/quickstart)
5. Primera sesion test sandbox (gratis, no consume credits) - sandbox profile especifico
6. Activacion produccion - notificacion ack
7. Primer behavior run real - observamos en backstage los primeros 50 runs
8. SLA informal first-week: si > 2 incidentes, refund + post-mortem
```

Tiempo objetivo desde signup a primera sesion: < 60 minutos (KPI).

## Sales / soporte ops

- 1 persona dedicada Q1-Q2 (puede ser founder), 2 personas Q3-Q4.
- Canal soporte: Telegram bot + Signal DM para incidents.
- Tickets respondidos < 4h en business hours (CET), < 24h fuera.
- No hay sistema de tickets formal (Zendesk, Intercom). Telegram + sheet interno.

## OPSEC en GTM

- Brand del spinoff distinta del brand del operador interno (entidades legales separadas, infra logicamente separada, mismas personas en background pero no en front).
- Nadie en sales communications usa nombre real ni LinkedIn personal.
- Pago a contratistas externos (legal, dev marketplace) solo via crypto desde wallet operativa del spinoff.
- DNS, hosting, CDN del spinoff en proveedores diferentes a los del operador interno (Cloudflare account separado, registrar separado).

## Riesgo de brand contamination — mitigaciones

- Si un cliente del SaaS recibe takedown DSP por practica desproporcionada, el blast radius queda en su infra (su catalogo, sus cuentas) y no toca al SaaS infra.
- Si el SaaS sufre takedown legal/proveedor, el operador interno no se ve afectado (entidades legales y proveedores compartmentalizados).
- TOS explicita que cliente es unico responsable del uso final del motor.
