# 04 — Plan de rollout

## Estructura general

6 sprints x 4 semanas = 24 semanas. Cada sprint termina en un gate cuantitativo que decide promocion/rollback. Al cierre del sprint 6 los 3 modelos estan al 100% del catalogo (excluyendo holdout permanente del 5%).

Roles minimos: 1 ML engineer (lead) + 1 backend engineer (integracion Temporal/Postgres/ClickHouse) + soporte parcial del operador (revision de divergencias en canary).

## Sprint 1 (semanas 1-4) — Backfill historico + LRV v0

### Objetivo
Tener un dataset de training reproducible y un modelo LRV v0 entrenado, sin despliegue.

### Entregables
- `BackfillCohort14dFeatures` workflow ejecutado sobre 12 meses historicos.
- Auditoria de cobertura: ≥ 95% tracks elegibles con cohort completo. Tracks excluidos (proxy fail historico, etc) listados con razon.
- `MaterializeLrvTarget` para mismo periodo.
- Notebook `spikes/year-2/lrv_regressor_poc.py` ejecutable sobre datos reales (no solo sinteticos) con EDA basica + baseline LightGBM + reporte MAE.
- Documento de hand-off con: feature dictionary, distribucion target, sesgos detectados.

### Gate de salida
- `MAE_baseline_LightGBM` sobre split temporal: < 35% (holgura sobre target final 25%).
- Cobertura holdout permanente registrada y auditada.
- Tiempo de training reproducible: < 10 min en infra existente.

### No-gate
Si MAE > 40% al final del sprint: NO se sigue al sprint 2. Se reabre feature engineering 2 semanas adicionales.

## Sprint 2 (semanas 5-8) — Shadow mode

### Objetivo
Modelo LRV produciendo predicciones diariamente sobre tracks reales, **sin actuar sobre catalogo**. Solo se loggean predicciones para validar contra ground truth.

### Entregables
- Workflow Temporal `RunNightlyDecisionBatch` desplegado en modo `SHADOW`.
- Tabla `ml_audit.shadow_predictions` con predicciones diarias.
- Job `MaterializeLrvTarget` corriendo con SLA de 75d (release_date + 75d) confiable.
- Dashboard: pestaña Year-2 ML con grafica MAE rolling 7d / 14d / 28d, coverage, distribucion residuals por nicho.
- Niche affinity v0 entrenado (no usado aun, solo evaluado).

### Gate de salida
- `MAE_holdout` rolling 28d: < 28% (margen de 3% sobre target 25%).
- Coverage `[p10, p90]`: ∈ [0.76, 0.84].
- Estabilidad de predicciones: stddev de prediccion del mismo track entre runs consecutivos < 8% relativo (sin reentrenamiento).
- Niche affinity: top-5 predicho cubre >= 60% de los nichos top-5 reales del cohort observado de Sprint 2.

### No-gate
- Si MAE > 30%: rollback shadow, retraining con features adicionales (analisis residuals).
- Si coverage fuera de banda: recalibrar quantiles antes de canary.

## Sprint 3 (semanas 9-12) — Canary 10%

### Objetivo
Activar `RunNightlyDecisionBatch` en modo `CANARY` sobre 10% del catalogo activo. El otro 90% sigue politica humana (control). Holdout 5% permanece intocado.

### Entregables
- Asignacion deterministica `track_id` -> `bucket_canary` (10%) o `bucket_control` (85%) o `bucket_holdout` (5%).
- Auditoria semanal: divergencia decision auto vs humana, justificacion en casos de override.
- Alertas Slack/Telegram cuando una decision auto contradice fuertemente al humano (`abs(LRV_predicho - LRV_humano_estimado) > 2x`).
- Investment optimizer (bandit) corriendo solo en simulacion offline.

### Gate de salida (semana 12, t = 60d desde primera decision auto)
- `K1 (MAE holdout)` < 25%.
- `K4 (% underperformers retirados pre-D90)` en canary >= 70% (target final 80% al sprint 6).
- `K5 lift ROI cohort canary vs control` (proyectado, datos parciales): >= 15% (target final 30%).
- `K10 stability`: < 8% flip rate en canary.
- 0 incidentes catastroficos: ningun track con `expected_lrv > 95th percentil` mandado a `RETIRE`.

### No-gate
- Si lift ROI proyectado < 0% (canary peor que control): rollback INMEDIATO a politica humana, post-mortem de 2 semanas, reintento.
- Si coverage de inferencia diaria < 99%: bloqueo expansion.

## Sprint 4 (semanas 13-16) — Canary 30% + bandit shadow

### Objetivo
Expandir canary a 30%. Activar bandit en shadow (recomienda budget pero no asigna). Niche affinity informa lote produccion siguiente con A/B vs heuristica humana.

### Entregables
- Bandit shadow loggeando recomendaciones vs decisiones humanas budget.
- Lote produccion mes split: 50% recomendado por niche affinity, 50% recomendado por humano (A/B controlado).
- Metricas de bandit: regret simulado vs oraculo retrospectivo, exploration ratio.
- Auto-retrain trigger conectado: si `MAE_rolling_7d > 0.30`, dispara retrain en 24h.

### Gate de salida
- `K1 MAE` < 24% en holdout.
- `K3 % renovado` mes-12 = en banda [25%, 50%].
- `K6 % decisiones auto sin override` en canary 30%: >= 80%.
- Bandit regret simulado < 20% del oraculo.

## Sprint 5 (semanas 17-20) — Canary 70% + bandit canary 30%

### Objetivo
Catalogo activo: 70% bajo decisiones auto (LRV+rules), 30% bajo bandit en vivo. Resto control + holdout.

### Entregables
- Bandit produciendo budget allocations reales sobre 30% catalogo.
- Comparacion ROI bandit vs heuristica fija (`bucket=25` por default) sobre subgrupo control.
- Auditoria mensual de holdout: confirmar que metrica MAE sobre holdout es comparable a in-sample (no hay leakage).
- Documentacion de runbooks operativos.

### Gate de salida
- `K1` < 22% en holdout.
- `K5 ROI lift cohort` (datos reales 60d cerrados): >= 25%.
- Bandit regret real < heuristica fija en >= 60% de los nichos.
- 0 issues de seguridad / leakage / datos contaminados.

## Sprint 6 (semanas 21-24) — Full rollout

### Objetivo
100% catalogo activo (excluyendo holdout 5% permanente) bajo decisiones auto + bandit. Operador humano queda como vetador, no decisor.

### Entregables
- Promocion final con anuncio interno de cambio de politica.
- Runbooks finales para operador.
- Plan de retraining mensual y dashboards consolidados.
- Reporte ejecutivo Año 2 con KPIs reales contra targets.

### Gate de salida
- `K1` < 22%.
- `K3` ∈ [30%, 50%].
- `K4` >= 80%.
- `K5` >= 30%.
- `K6` >= 70%.
- `K10` < 5%.

## Auto-retrain trigger

Configurado desde Sprint 4 en adelante. Logic:

```
if MAE_holdout_rolling_7d > 0.30:
    fire("retrain_due_to_drift")
elif data_drift_score(features_today, features_last_30d) > 0.4:
    fire("retrain_due_to_data_drift")
elif coverage_rolling_28d not in [0.75, 0.85]:
    fire("recalibration_due_to_coverage")
```

Retrain workflow es el mismo que weekly cron pero ejecutado on-demand y con `priority=high`. SLA: nuevo modelo promovido en < 24h desde el trigger.

## Rollback procedure

En cualquier sprint, si gate falla:

1. Workflow `RunNightlyDecisionBatch` cambia a modo `SHADOW` automaticamente.
2. Postgres `tracks.action` revertido al ultimo estado humano via tabla `ml_audit.action_history`.
3. Bandit congelado.
4. Alerta a operador + post-mortem en 7 dias.
5. No se reintenta promocion sin pasar el gate fallado en cohort fresca.

## Definicion de "control humano"

El subgrupo `control` recibe decisiones del operador con la misma cadencia y herramientas que en Año 1. Para no contaminarlo:

- Decisiones auto del canary NO se exponen al operador antes de que decida sobre control.
- Reportes humano-vs-ML solo se generan post-decision (loggeados en `ml_audit.diverging_decisions`).
- Operador firma quincenalmente que no consulta predicciones ML al decidir control. Auditoria en logs de acceso al dashboard ML.

Este compromiso es necesario para que K5 (ROI lift) sea defendible cuantitativamente.
