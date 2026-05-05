# Postmortem — incidente {INCIDENT_ID}

> Llenar dentro de las 24h del cierre del incidente. Conservar en
> `/var/log/streaming-bot-dr/{INCIDENT_ID}/postmortem.md` y
> archivar copia en MinIO bucket `dr/postmortems/`.
>
> No es un documento de blame: es un documento de aprendizaje y de
> mejora del runbook.

---

## Identificacion

- **Incident ID**: {INCIDENT_ID}
- **Escenario DR**: DR-{1|2|3|4|5|6} (referencia `scenarios.md`)
- **Trigger time (UTC)**: YYYY-MM-DDThh:mm:ssZ
- **Detection time (UTC)**: YYYY-MM-DDThh:mm:ssZ
- **Resolution time (UTC)**: YYYY-MM-DDThh:mm:ssZ
- **Time to detect (TTD)**: ___ min
- **Time to mitigate (TTM)**: ___ min
- **Time to recover (TTR)**: ___ min
- **Total downtime impacto**: ___ min
- **Severity** (S1=critico, S2=alto, S3=medio, S4=bajo): __

## Equipo involucrado

| Rol | Nombre / handle | Tiempo invertido (h) |
|-----|------------------|------------------------|
| Incident Commander |  |  |
| Tech recovery |  |  |
| Comms |  |  |
| Legal coord (si aplica) |  |  |

## Resumen ejecutivo (parrafo)

> 1-2 parrafos que un operador externo entenderia. Que paso. Que
> impacto. Como se resolvio. Que aprendimos.

## Impacto medible

| Dimension | Valor |
|-----------|-------|
| Cuentas afectadas | __ |
| Tracks afectados | __ |
| Streams perdidos (estimacion) | __ |
| Revenue perdido (USD estimado) | __ |
| Cuentas banneadas no recoverable | __ |
| Modems flagged_count incrementado | __ |
| Workflows interrumpidos | __ |
| Workflows perdidos sin retry | __ |
| Tiempo dashboard down | __ min |
| Tiempo API down | __ min |

## Cronologia

| Time UTC | Evento | Quien | Source (log/Telegram/dashboard) |
|----------|--------|-------|---------------------------------|
| HH:MM:SS | Trigger inicial | system | Prometheus alert "X" |
| HH:MM:SS | Deteccion humana | operador | Telegram dr-ops |
| HH:MM:SS | Decision: ejecutar runbook DR-X | IC | timeline.log |
| HH:MM:SS | Paso 1 ejecutado | IC | timeline.log |
| HH:MM:SS | ... | ... | ... |
| HH:MM:SS | Resolucion confirmada | IC | healthz / dashboard / KPIs |

## Root cause analysis

### What happened (descriptivo, sin culpa)
> Que sucedio en terminos tecnicos.

### Why (los 5 porques)
1. ____________________________
2. ____________________________
3. ____________________________
4. ____________________________
5. ____________________________

### Root cause definitivo

> Una frase precisa. Si hay multiples, prioriza por contribucion al
> impacto.

### Contributing factors (no es root pero amplifico)

- ____________________________
- ____________________________

## Detection

- **Como se detecto**: alerta automatica / manual / reporte
  externo / cliente.
- **TTD**: ___ min (objetivo: <5 min para S1, <30 min para S2).
- **Si TTD excede objetivo**, por que?
  - Falta de alerta especifica?
  - Alerta existia pero estaba silenced?
  - Alerta llego al canal incorrecto?
  - Alerta llego pero fue ignorada?

## Response

- **Time-to-acknowledge** (operador respondio a la alerta): ___ min.
- **Runbook seguido**: si / no, cual?
- **Si NO se siguio runbook, por que?**
- **Si se siguio runbook, fue suficiente?** Detalla pasos faltantes
  o ambiguos.

## Mitigation

- **Que mitigation se aplico**:
- **Time-to-mitigate** (sintoma controlado, no root cause): ___ min.
- **Mitigation fue suficiente para limitar el impacto?**

## Recovery

- **Que recovery acciones se ejecutaron**:
- **Time-to-recover** (sistema vuelve a steady state): ___ min.
- **Datos perdidos / corruption?** Cuanto exactamente?

## Action items (prioridad alta primero)

| Accion | Owner | Plazo | Severity |
|--------|-------|-------|----------|
| (Fix de root cause si aplica) |  | T+__ dias | critical |
| (Mejora del runbook con paso faltante) |  | T+__ dias | high |
| (Agregar alerta que falto) |  | T+__ dias | high |
| (Doc o training si requerido) |  | T+__ dias | medium |
| (Cambio infra preventivo) |  | T+__ dias | medium |
| (Mejora monitoring) |  | T+__ dias | low |

## What went well (NO opcional)

> Min 3 cosas que SI funcionaron. Si solo se te ocurre 1, has un
> esfuerzo mas. Equipo necesita ver esto para mantener motivacion.

1. ____________________________
2. ____________________________
3. ____________________________

## What went poorly

1. ____________________________
2. ____________________________
3. ____________________________

## Where we got lucky

> Que pudo salir peor y no salio. Importante para identificar
> riesgos latentes.

1. ____________________________

## Comunicacion durante el incidente

- **Stakeholders externos notificados (si aplica)**: tax lawyer /
  registered agent / banking compliance? Cuando y por que canal?
- **Comunicacion interna fue suficiente?** Quien quedo fuera del
  loop?

## Decisiones bajo presion

> Lista de decisiones tomadas bajo presion, con rationale. Util
> para postmortem cultural.

| Decision | Rationale | En retrospectiva fue correcta? |
|----------|-----------|--------------------------------|
| (ej: pause global vs pause per-cluster) | (ej: priorizar contencion) | si/no, por que |

## Costo monetario del incidente

| Componente | USD |
|------------|-----|
| Revenue perdido directo | __ |
| Cripto OTC fee si freeze (DR-4) | __ |
| Tax lawyer hours | __ |
| Recursos infra extra (Hetzner emergency, ProxyEmpire overflow) | __ |
| Cuentas reposicion (signup nuevas + warming) | __ |
| **Total** | __ |

## Adjuntos

- [ ] `timeline.log` capturado en `/var/log/streaming-bot-dr/{INCIDENT_ID}/`
- [ ] Health snapshot pre-incidente (si disponible)
- [ ] Health snapshot post-recovery
- [ ] Grafana dashboard PNGs relevantes
- [ ] Logs Postgres / ClickHouse / Temporal extraidos
- [ ] Telegram dr-ops thread completo (text export)
- [ ] Capturas UI de dashboards externos (Hetzner, banking, distros) si
  aplica
- [ ] Si DR-4: copia del comunicado del banking + tickets soporte

## Sign-off

- **Postmortem author**: ________________________  Date: ________
- **Reviewed by (operador secundario / contractor)**: ____________  Date: ________

> Una vez sign-off, archivar copia en `dr/postmortems/{INCIDENT_ID}.md`
> en MinIO + sync a Backblaze B2 (replica geografica).

---

## Sustainability check (NO opcional)

Despues de cada postmortem, anadir las acciones a una sola lista
maestra `dr-action-items.md` y revisar status mensualmente. Sin
esto, el postmortem es teatro.

- [ ] Action items agregados a backlog
- [ ] Acciones critical asignadas con plazo concreto
- [ ] Calendario de review mensual de pending action items confirmado
- [ ] Si tres postmortems consecutivos identifican el mismo gap:
  escalar a redisenar el componente, no parchar el runbook
