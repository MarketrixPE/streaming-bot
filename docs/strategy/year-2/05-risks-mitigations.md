# 05 — Riesgos y mitigaciones

## Filosofia

Cada riesgo tiene: (1) probabilidad estimada, (2) impacto cuantificado, (3) detector concreto, (4) mitigacion accionable, (5) owner.

No se aceptan mitigaciones del tipo "monitorear de cerca". Toda mitigacion debe ser ejecutable y verificable.

## R1 — Feedback loop / autoreferencia del modelo

### Descripcion
El modelo aprende sobre datos generados parcialmente por sus propias decisiones (un track al que el modelo retiro tempranamente nunca tendra LRV observado completo, sesgando entrenamientos posteriores hacia confirmar la decision de retiro).

### Probabilidad / impacto
Alta / Alto. Sin mitigacion el modelo deriva en 2-3 ciclos de retraining hacia "todo es underperformer".

### Detector
- KPI K11 (holdout integrity) auditado mensualmente.
- Metric `divergence_holdout_vs_canary_residuals_distribution` (KS test): si se separan, alerta.

### Mitigacion
- **Holdout permanente 5%**: nunca tocado por ML. Asignacion deterministica `is_holdout(track_id)` ([02-data-model.md](./02-data-model.md)). Auditoria mensual del hash del set.
- **Counterfactual exploration 2%**: una vez al mes, 2% de tracks con `action == RETIRE` (segun modelo) reciben override manual a `KEEP_INVESTING` para observar LRV real. Esto contribuye a corregir sesgos selectivos.
- **No reentrenar sobre tracks recientes con accion ML aplicada**: filtro `min_age_days_at_target_observed = 60d` en training.

### Owner
ML engineer lead.

### Test de aceptacion
Reporte mensual `holdout_proof.md` autogenerado con: hash del set, cantidad, MAE_holdout vs MAE_canary, KS test stat, p-value.

## R2 — Algorithmic drift en plataformas DSP (Spotify cambia algoritmo)

### Descripcion
Spotify, Deezer, SoundCloud cambian sus algoritmos / antifraud / playlist surfacing. El historico deja de ser predictivo.

### Probabilidad / impacto
Alta / Medio-Alto. Historicamente Spotify reescribe Discovery Weekly cada 6-12 meses. Beatdapp + Pex se actualizan trimestralmente.

### Detector
- `lrv_pred_mae_rolling_7d` Prometheus: si > 30% sostenido > 7 dias, drift signal.
- `feature_distribution_drift_score` (Kolmogorov-Smirnov sobre cohort_14d features ultimos 30d vs baseline 90d): trigger automatico.
- Alerta separada por DSP: `mae_per_dsp` para diagnosticar source-specifically.

### Mitigacion
- **Auto-retrain trigger** (ver [04-rollout-plan.md](./04-rollout-plan.md)) con SLA < 24h.
- **Modelos DSP-aware**: aunque no entrenamos un modelo por DSP, las features DSP-published estan dummy-encoded. Permite fitting reactivo a cambios de un DSP especifico sin tocar arquitectura.
- **Window de training adaptativo**: si drift detectado, retrain con window 60d (no 90d) durante 60 dias.
- **News watch operativo**: lista RSS de blogs antifraud (Beatdapp, Music Business Worldwide) en Slack, evento de cambio mayor dispara revision proactiva.

### Owner
ML engineer + operador.

### Test de aceptacion
Drift simulation cada trimestre: corruptamos 10% de features (jitter aleatorio +-30%) y verificamos que trigger dispara en < 24h.

## R3 — Saturacion de nichos winners

### Descripcion
Niche affinity recomienda nichos hot. Operador produce lotes grandes en esos nichos. La saturacion erosiona el LRV/track del nicho. El modelo, retrasado por target lag de 60d, sigue recomendando.

### Probabilidad / impacto
Alta / Medio. Sin mitigacion: en 60-90 dias erosion 20-40% LRV/track en nichos top.

### Detector
- Feature `niche_saturation_score` ya en cohort_14d (rolling supply / demand del nicho).
- Metric `lrv_per_track_by_niche_28d_vs_90d` cae > 25%: alerta.

### Mitigacion
- **Niche affinity penaliza saturacion explicitamente**: feature `same_niche_releases_last_30d` + `niche_saturation_score` con interaction term explicita en el clasificador.
- **Cap supply por nicho**: hard cap `max_releases_per_niche_per_month = f(saturation_score)`. Si saturation > 0.7, cap = lote_actual_x_0.5.
- **Diversificacion forzada**: cada lote mensual debe distribuir produccion entre >= 5 nichos top-K, no concentrarse > 40% en uno.
- **Counterfactual nicho**: cada mes 1 nicho rezagado recibe lote pequeño (5-10 tracks) para detectar sleepers no captados por modelo.

### Owner
Operador + ML engineer.

### Test de aceptacion
Test mensual: graficar `LRV_promedio_nicho` vs `releases_30d_nicho`. Pendiente debe ser plana o positiva en >= 80% de los nichos top-10.

## R4 — Calidad de proxies / cohort fail (datos basura entran en training)

### Descripcion
Tracks con cohort_14d construido sobre proxies fallidos / cuentas baneadas tienen senales degradadas que nada tienen que ver con la calidad real del track.

### Probabilidad / impacto
Media / Alto. Si 5%+ de tracks tienen cohort degradado, MAE se infla 5-10pp.

### Detector
- Feature `geo_unknown_share` (% plays sin geo confiable).
- Auditoria semanal cruz: tracks con `geo_unknown_share > 0.3` y comparar LRV_60d vs LRV_predicho.
- Metric `cohort_quality_score` agregado a cada track antes de entrar a feature mart.

### Mitigacion
- **Filtro `cohort_quality_score >= 0.8`** en training y en inferencia. Tracks bajo umbral marcados como `unscored` y enviados a fallback humano.
- **Backfill correctivo**: si un proxy falla retroactivamente, marcar tracks afectados y reentrenar features post-fix.
- **Sanity check diario**: `unscored_tracks_pct < 5%` o alerta.

### Owner
Backend engineer + ML engineer.

## R5 — Cold start de nicho nuevo

### Descripcion
Operador prueba un nicho sin historico (ej. ASMR-binaural). LRV regressor predice mal porque no ha visto ese nicho.

### Probabilidad / impacto
Media / Bajo. Solo afecta lotes experimentales (~10% del catalogo).

### Detector
- Niche affinity model marca `confidence < 0.4` para nichos nuevos.
- Heuristic: niche con `same_niche_total_history_count < 30 tracks`: cold-start.

### Mitigacion
- **Bypass automatico para cold-start**: tracks de nichos cold-start usan policy heuristica conservadora (`bucket=25`, `action=KEEP_INVESTING`) por 30 dias y solo entran en LRV regressor a partir del dia 60 (con su LRV ya parcialmente observado como prior).
- **Etiqueta `cold_start = true`** en `tracks` Postgres. Se loggean separadamente para diagnostico.

### Owner
ML engineer.

## R6 — Ataque adversarial / data poisoning interno

### Descripcion
Bug o accion maliciosa inyecta eventos artificiales en `stream_events` para inflar/deflactar LRV de tracks especificos.

### Probabilidad / impacto
Baja / Alto. Concretamente: un dev con acceso DB modifica targets para que su track favorito gane budget bandit.

### Detector
- Audit log `ml_audit.feature_mart_writes` con identidad del proceso.
- Metric `events_per_track_per_day` con baseline + anomaly detection (igual al motor antifraud Año 1).
- Hash de target `lrv_60d_cents` por mes en `ml_audit.target_hashes`. Cambios despues de cierre de mes alarman.

### Mitigacion
- **Append-only en `royalty_observations`** y eventos. Cualquier rewrite requiere migration aprobada.
- **Reviews 2-eyes** sobre cualquier cambio en queries de feature mart.
- **Replay de target**: cron mensual que recomputa `lrv_60d_cents` desde `royalty_observations` y compara con tabla materializada. Diff > 0.1% alarma.

### Owner
Backend engineer + security.

## R7 — Sobre-confianza en intervalo predicho

### Descripcion
Operador / sistema confia ciegamente en `[p10, p90]`. Si la calibracion deriva sin que se note, decisiones HARVEST/RETIRE se toman con margen falso.

### Probabilidad / impacto
Media / Medio. Decisiones erroneas en tracks borderline pueden costar 10-15% LRV recuperable.

### Detector
- Coverage rolling 28d: la fraccion observada de `actual ∈ [p10, p90]` debe estar en `[0.75, 0.85]`.
- Si fuera de banda: alerta inmediata.

### Mitigacion
- **Recalibracion isotonic post-prediction** ejecutada con cada retrain.
- **Decisiones borderline conservadoras**: si `expected_lrv_60d_p50` ∈ `[breakeven * 0.9, breakeven * 1.1]`, defaultear a `KEEP_INVESTING` 14 dias mas y reescorar.
- **Banda de incertidumbre visible** en dashboard: el operador siempre ve p10/p50/p90, no solo p50.

### Owner
ML engineer.

## R8 — Drop temporal de catalogo (takedown masivo)

### Descripcion
Un distribuidor sufre takedown / Spotify retira musica masivamente (caso Boomy 2023). El catalogo activo cae 30-50% en pocos dias. El feature mart se desbalancea.

### Probabilidad / impacto
Media / Alto.

### Detector
- KPI Año 1 ya en lugar (`takedown_rate_per_distro_per_month`). Conectar como input al ML pipeline.

### Mitigacion
- **Pause auto-decisions** durante eventos de takedown masivo: si `takedown_rate_24h > 5%`, modo SHADOW automatico durante 7 dias.
- **Re-baseline cohort_14d_mean** post-evento, retraining con window reducida.

### Owner
Operador + ML engineer.

## R9 — Costos infra de training fuera de control

### Descripcion
Auto-retrain frecuente + Optuna 60 trials se vuelven caros si dataset crece a millones de tracks.

### Probabilidad / impacto
Baja / Bajo (escala de Año 2: ~50k-100k tracks). Mantenible.

### Mitigacion
- **Cap weekly retrain budget**: max 30 min compute. Si excede, reduce trials Optuna a 20.
- **Subsampling estratificado** sobre tracks viejos (>180d): max 1 por nicho-mes.

### Owner
ML engineer.

## R10 — Operador humano se desconecta

### Descripcion
Con automatizacion >70%, el operador deja de revisar decisiones. Bug subtil pasa desapercibido por semanas.

### Probabilidad / impacto
Media / Medio.

### Mitigacion
- **Sample auditoria diario obligatorio**: 20 decisiones aleatorias mostradas al operador en dashboard, requiere "ack" o flag.
- **Alertas activas Slack/Telegram**: cualquier divergencia abrupta entre cohorts ML vs holdout.
- **Reporte ejecutivo semanal autogenerado**: distribuido a operador + stakeholder, con highlights de casos extremos.

### Owner
Operador.

## Tabla resumen

| Riesgo | Probabilidad | Impacto | Mitigacion principal | KPI defensivo |
|---|---|---|---|---|
| R1 Feedback loop | Alta | Alto | Holdout 5% permanente | K11 |
| R2 DSP drift | Alta | M-Alto | Auto-retrain < 24h | K9 |
| R3 Niche saturation | Alta | Medio | Cap supply + penalizacion | LRV/track 28d vs 90d |
| R4 Cohort calidad | Media | Alto | cohort_quality_score filter | unscored_pct < 5% |
| R5 Cold start | Media | Bajo | Heuristica fallback | nichos n<30 marcados |
| R6 Data poisoning | Baja | Alto | Append-only + 2-eyes | target hash diff |
| R7 Calibracion | Media | Medio | Recalibracion + bandas visibles | coverage in band |
| R8 Takedown masivo | Media | Alto | Pause auto-decisions 7d | takedown_rate_24h |
| R9 Costos training | Baja | Bajo | Cap budget + subsampling | training_cost_weekly |
| R10 Operador desconectado | Media | Medio | Auditoria sample diaria | acks_per_day |
