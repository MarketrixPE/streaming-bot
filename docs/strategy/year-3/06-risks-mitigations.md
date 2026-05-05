# 06 — Riesgos y mitigaciones

## Filosofia

Cada riesgo: probabilidad estimada, impacto economico cuantificado, detector concreto, mitigacion ejecutable, owner. Mismo standard que [year-2/05-risks-mitigations.md](../year-2/05-risks-mitigations.md).

## R1 — Cannibalizacion (cliente nos compite con nuestra propia palanca)

### Descripcion
Un tenant del SaaS opera un catalogo en el mismo nicho que nuestro operador interno y, gracias al motor que le vendemos, captura share que de otra forma seria nuestro.

### Probabilidad / impacto
Media / Bajo-Medio. Estimacion: < 5% impact en ingresos del operador interno por tenant en mismo nicho.

### Por que el riesgo es bounded
- El motor SaaS es solo una parte del stack competitivo. El cliente sigue dependiendo de su catalogo (decisiones creativas), sus cuentas, sus proxies, y su capacidad de produccion. Estas son las palancas dominantes.
- Nuestro operador interno tiene ventajas adicionales no vendibles: corpus completo (no anonimizado) para entrenar profiles propios, ML-driven catalog optimization Año 2, multi-tier geo router con scoring per-track, granja propia.
- El SaaS pricing al cliente (`$0.05/$0.20`) crea un piso de costo marginal que NO podemos bajar para nosotros mismos sin perder margen del SaaS. Pero el operador interno NO paga esos precios al SaaS — usa el motor a costo marginal real (~$0.026/$0.054). Es decir, mantenemos una ventaja de costo del 50%+ vs cualquier tenant.

### Detector
- Reporte mensual: distribucion de tenants por nicho declarado (auto-clasificable) cruzado con nuestros nichos top-10 internos. Si > 25% del revenue spinoff viene de tenants en nuestros nichos top-3, alerta.
- Lift de bandit interno: si revenue interno cae > 10% trimestre y revenue spinoff sube en mismos nichos, investigar.

### Mitigacion
- **Pricing competitivo en infra impide spread alto**: el cliente paga $0.05/$0.20 — para revender contra nosotros con margen necesita superarnos en alguno de cuentas/proxies/catalogo, donde tiene desventaja estructural.
- **Veto comercial interno**: el founder puede negarse a aceptar un tenant que solicita expansion en nicho-clave. Documentado en TOS como discrecional.
- **Pricing tier Volume es negociable**: para tenants grandes en nichos no-conflictivos podemos premiar lealtad con pricing premium; para tenants en nichos conflictivos mantenemos pricing standard.

### Owner
Founder.

### Test de aceptacion
Reporte trimestral de overlap nicho-tenant vs nicho-interno. Action si overlap > umbral.

## R2 — Exposure legal por "vender pickaxes" en mercado gris

### Descripcion
Caso analogo a `US v. Smith`: una jurisdiccion (US, EU) puede tipificar la venta de infraestructura claramente diseñada para violar TOS de DSPs como complicity criminal o delito de ayuda a fraude electronico.

### Probabilidad / impacto
Media (3-5 anos horizonte) / Alto (cierre operacional en jurisdiccion afectada, multa, exposure personal si identidad expuesta).

### Detector
- Monitoreo proactivo: tracking causes legales emergentes (Smith case, Beatdapp lawsuits, IFPI initiatives) via firma legal especializada en US / EU.
- Watchlist trimestral: nuevos consent orders DOJ, decisiones EU sobre fraud digital.

### Mitigacion
- **Setup separado en BVI/RAK**: entidad legal del spinoff distinta del operador interno, con domicilio en jurisdicciones offshore (BVI: International Business Companies Act; RAK ICC: discrecion mayor). Documentos legales nunca tocan US/EU corporativamente.
- **TOS limita uso**: redaccion explicita "intended for automated testing of public web services". Operadores que lo usen para violar TOS DSP son responsables exclusivos.
- **No logging granular de actividades cliente**: no almacenamos URLs especificas que el cliente visita, no almacenamos external_ids de tracks/playlists, no almacenamos creds. Lo que persistimos: metricas agregadas de session (duration, anomalies count, success status). Reduce significativamente el "data" disponible en discovery legal.
- **Compartmentalizacion personal**: nadie en la operacion del spinoff usa identidad real ni en banking ni en comunicaciones. Wallets cripto pseudonymous.
- **Plan de cierre rapido**: runbook de cierre operacional spinoff en 72h si caso emerge en US/EU. Snapshots desactivados, dominios cancelados, comunicacion a tenants via Telegram con migration window.

### Owner
Founder + asesor legal offshore retainer.

### Test de aceptacion
Auditoria legal anual: setup + TOS + compliance posture revisada por firma offshore.

## R3 — Tenant malicioso usa motor para ataque a infra third-party

### Descripcion
Un tenant abuse el motor stealth para credentials stuffing, scraping ofensivo, doxxing, ataque a startups, etc. Esto crearia exposure legal directa al SaaS.

### Probabilidad / impacto
Media / Alto. Caso real existe en industria (proxy providers han enfrentado consecuencias).

### Detector
- Anomaly detection sobre patrones de uso por tenant: heuristic `requests/min > 30x baseline`, `targets unique > 10k/dia`, `targets in TLD blacklisted` (gov, mil, financial servicios sensibles).
- Reportes externos: monitoreo abuse@ inbox, blacklists publicas (Spamhaus, AbuseIPDB).

### Mitigacion
- **TOS prohibicion explicita**: lista negra de targets (gobiernos, financial institutions, healthcare, infraestructura critica), violacion = ban inmediato + perdida de credits.
- **TLD-level filtering automatico**: el motor rechaza navegacion a TLDs en blacklist. Lista mantenida centralizada con politicas estrictas.
- **Volume thresholds**: tenant nuevo recibe rate limits estrictos (10 sesiones/min) hasta acumular 30 dias de buen comportamiento.
- **Reportes abuse@**: respuesta estandar < 24h, ban inmediato si caso se confirma. Cooperar con LE solo bajo court order valida en jurisdiccion offshore.

### Owner
Founder + community manager (operativo).

### Test de aceptacion
Drill mensual: simulacion abuse report -> respuesta + ban + post-mortem en < 24h.

## R4 — Detection rate del motor empeora (DSPs cierran loopholes)

### Descripcion
DSPs (Spotify, Deezer) actualizan antifraud y nuestros profiles dejan de pasar. Tenants ven bans masivos, churn explota.

### Probabilidad / impacto
Alta (recurrente, 1-2 veces/ano por DSP) / Medio.

### Detector
- KPI por tenant: `bans_per_session_28d` rolling. Si sube > 50% vs baseline en cluster de tenants, alerta.
- Comparacion interno vs externo: si nuestro operador interno sufre bans pero externos no (o viceversa), problema-source diferente.
- Watch news antifraud (Beatdapp, IFPI) para early warning.

### Mitigacion
- **Auto-retrain profiles**: profile_v_actual se rentrena semanalmente con corpus mas reciente. Nuevo profile rolled out gradualmente (10% canary -> 100% en 5 dias).
- **Multi-engine fallback**: si Patchright falla, switch automatico a Camoufox para profile especifico. Cobertura redundante.
- **Notificacion proactiva tenants**: si detection_rate sube, notificar tenants con recomendacion de profile alternativo o rate limit reduction. Mantiene confianza.
- **SLA informal de "credit refund parcial" si SUS bans suben > 40% en 7 dias por culpa nuestra demostrable**: politica blanda pero firma confianza.

### Owner
ML engineer + ops.

### Test de aceptacion
Disaster drill semestral: simular antifraud update agresivo (bloqueo profile X de un DSP), verificar SLA recovery < 5 dias.

## R5 — Fuga de corpus behavioral (data exfiltration)

### Descripcion
Un dev malicioso o breach interno expone corpus behavioral entrenamiento. Pierde defensibilidad y, peor, quizas contiene fragmentos de sesiones recuperables.

### Probabilidad / impacto
Baja / Alto (perdida de moat).

### Detector
- DLP en S3 / MinIO buckets de corpus.
- Audit logs accesos al corpus + 2-eyes en queries grandes.

### Mitigacion
- **Corpus encriptado at rest** con clave en HashiCorp Vault local. Acceso solo desde batch ETL container con auth corta-vida.
- **Pipeline anonymizacion en CI**: corpus que entra a training nunca contiene info identificadora ([04-architecture-spinoff.md](./04-architecture-spinoff.md) seccion anonimizacion).
- **Watermarks en profiles**: cada profile generado tiene un watermark indetectable que permite atribuir corpus si se filtra.
- **Backups offline encriptados**: no quedan accesibles en network 24/7.

### Owner
Backend lead + security.

## R6 — Concentracion de revenue en pocos tenants

### Descripcion
Top-3 tenants representan > 50% del revenue. Si pierde uno, churn impactante.

### Probabilidad / impacto
Media / Medio.

### Detector
- Reporte mensual `% revenue from top-N tenants`.
- Alarma si top-3 > 40%.

### Mitigacion
- **KPI publico**: top-3 < 35% como objetivo Mes 12.
- **Pricing tier Volume con cap mensual blando**: si un tenant > $50k/mes, pricing converge a 92% del standard (no descuento agresivo). Reduce dependencia.
- **Diversification programs**: incentivos para crecer ancho de banda (tier Pro mid-tier).

### Owner
Founder + ops.

## R7 — BTCPay self-hosted falla / fondos congelados temporalmente

### Descripcion
BTCPay server tiene downtime; tenants no pueden recargar; o transaccion legitima queda pending dias.

### Probabilidad / impacto
Baja / Medio.

### Mitigacion
- **BTCPay HA** con 2 nodos en regiones distintas, fallover DNS.
- **Reserva manual**: tenants pueden enviar tx directa a wallet hot conocida y se acreditan manualmente con auditoria. Backup procedure.
- **Monitoring transacciones blockchain** independiente (Etherscan API watcher, Tron explorer) — no depender solo de BTCPay para deteccion.

### Owner
Backend lead.

## R8 — Multi-tenancy data leakage (bug)

### Descripcion
Bug en RLS policy permite que tenant A vea data de tenant B (lista sesiones, metricas, logs).

### Probabilidad / impacto
Media (bugs de policies son comunes) / Alto (perdida de confianza, posible litigation).

### Detector
- Tests integration en CI: cada release ejecuta suite que valida policies. >100 cases.
- Monitoring on-prod: tabla `audit.policy_check_failures` registra cualquier query que devuelva rows con tenant_id distinto al esperado.

### Mitigacion
- **RLS por defecto en todas las tablas tenant-scoped + tests gating CI**.
- **2-eyes review obligatorio** para cualquier PR que toque policies o queries con tenant_id.
- **Linter custom** que rechaza queries en codigo backend sin filtro `tenant_id` explicito (incluso bajo set_config).
- **Bug bounty interno**: $1k cripto a cualquier dev que detecte un cross-tenant leak antes de prod.

### Owner
Backend lead + security.

### Test de aceptacion
Pen-test interno trimestral: dos tenants ficticios A y B, sweep de endpoints intentando leak. Resultado documentado.

## R9 — Operativo: mantenedor del Patchright/Camoufox abandonado

### Descripcion
Patchright o Camoufox dejan de mantenerse upstream. Sin parches, fingerprints quedan detectados rapidamente.

### Probabilidad / impacto
Baja-Media / Medio.

### Mitigacion
- **Fork interno** mantenido en repo privado del operador. Si upstream para, seguimos parcheando.
- **Diversificacion engines**: nodriver, undetected-chromedriver, otras alternativas con PoCs en spike de Año 1 ya validados.
- **Capacidad ML para predecir detecciones**: corpus + modelos behavioralalimentan heuristicas que detectan cuando un engine deja de pasar antes de que afecte tenants.

### Owner
ML engineer + backend lead.

## R10 — Soporte / community manager bottleneck

### Descripcion
Crecimiento tenants > 50 satura un solo community manager. Tickets sin respuesta, tenants churan.

### Probabilidad / impacto
Media / Medio.

### Mitigacion
- **Self-serve docs**: 80% de tickets potenciales resueltos en docs (provisioning, SDK, errores comunes, billing).
- **Telegram bot**: respuestas automaticas a tickets repetitivos (saldo, status, link doc relevante).
- **Escala personal**: contratar segundo CM en Mes 9 si tenants > 30. Tercero en Mes 12 si > 50.

### Owner
Founder.

## Tabla resumen

| Riesgo | Probabilidad | Impacto | Mitigacion principal | KPI defensivo |
|---|---|---|---|---|
| R1 Cannibalizacion | Media | Bajo-Medio | Pricing motor + ventaja costo interno | overlap nicho |
| R2 Exposure legal | Media | Alto | BVI/RAK + TOS + sin logs granulares | trimestral audit |
| R3 Tenant malicioso | Media | Alto | TLD blacklist + volume thresholds | abuse@ < 24h |
| R4 Detection rate | Alta | Medio | Auto-retrain profiles | bans/sess 28d |
| R5 Fuga corpus | Baja | Alto | Encryption + watermarks | DLP audit |
| R6 Concentracion revenue | Media | Medio | Cap voluntario top-3 | top-3 % |
| R7 BTCPay falla | Baja | Medio | HA + reserva manual | uptime |
| R8 Cross-tenant leak | Media | Alto | RLS + tests + 2-eyes | policy_check_failures |
| R9 Engines abandonados | Baja-Media | Medio | Fork + diversificacion | pass_rate engine |
| R10 Soporte bottleneck | Media | Medio | Docs + bot + escala | tickets/agent |
