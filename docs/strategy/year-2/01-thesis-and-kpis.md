# 01 — Tesis e hipotesis verificables, KPIs

## Tesis formal

Sea `T` un track con cohort de senales observado en `[release_date, release_date + 14d]`. Definimos:

- `LRV_60d(T)` = sumatoria de `royalty_observations.amount_cents` de `T` en `[release_date + 15d, release_date + 60d]`.
- `cohort_features(T)` = vector de senales del periodo 0-14d (plays, save_rate, geo_mix, playlist_adds, premium_ratio, save_velocity, skip_rate, queue_rate, etc — ver [02-data-model.md](./02-data-model.md)).
- `niche(T)`, `dsps(T)`, `distros(T)`, `production_cost(T)`, `cumulative_invest_streaming_cost(T, 14d)`.

**Tesis H0**:

> Existe una funcion `f_LRV: cohort_features × niche × dsps × distros × costs → R+` tal que `MAE(f_LRV(T), LRV_60d(T))` sobre un holdout estratificado representativo del catalogo es **< 25%** (relativo al ground truth medio).

**Tesis H1**:

> Existe una politica `pi(track) ∈ {KEEP_INVESTING, HARVEST, RETIRE}` derivada de `f_LRV` y de la curva de costo marginal, tal que aplicada al portafolio en Año 2 produce un **lift de ≥ 30% en ROI agregado** (royalty / costo total) vs. la politica humana de Año 1.

**Tesis H2**:

> Existe una funcion `f_niche: historico_operador × saturacion_actual → ranking nichos` tal que el lote de produccion N+1 informado por `f_niche` tiene un **LRV medio observado ≥ 15% mayor** que el lote N producido bajo decision humana.

H0, H1, H2 son falsables con experimentos descritos en [04-rollout-plan.md](./04-rollout-plan.md). Si fallan en shadow mode no se promueven a canary. Si fallan en canary se rollbackean.

## Hipotesis secundarias (instrumentables)

| Codigo | Hipotesis | Como se valida |
|---|---|---|
| HS1 | Las senales de los dias 1-7 ya contienen >70% de la varianza explicable de LRV. | Feature importance + shapley sobre split temporal |
| HS2 | save_rate_d7 y geo_mix superan a play_count_d7 en poder predictivo. | Permutation importance comparativa |
| HS3 | Tracks con playlist_adds_count >= 3 en d14 tienen distribucion LRV bimodal (hits vs flops). | KDE sobre subset, test Hartigan dip |
| HS4 | El bandit converge a >85% del oracle batch en ≤ 30 dias. | Regret simulado contra oraculo retrospectivo |
| HS5 | El modelo niche penaliza nichos saturados detecta caida >20% en LRV/track al pasar de 5 -> 50 tracks/mes en mismo nicho. | Pruebas controladas en 2 nichos |

## KPIs numericos (verificables, sin frases vagas)

### KPI primarios (gate go/no-go por sprint)

| ID | Definicion | Formula | Target | Cadencia |
|---|---|---|---|---|
| K1 | LRV prediction MAE holdout | `mean(abs(pred - actual)) / mean(actual)` | < 25% | Por release de modelo |
| K2 | LRV prediction P90 error | `quantile(abs(pred - actual)/actual, 0.9)` | < 50% | Por release de modelo |
| K3 | % portafolio renovado/mes | `tracks_publicados_30d / catalogo_activo_total` | ∈ [30%, 50%] | Mensual |
| K4 | % underperformers retirados pre-D90 | `tracks_RETIRE_aplicados_pre_d90 / tracks_underperformers_reales` | ≥ 80% | Mensual rolling |
| K5 | ROI cohort lift | `(royalty/cost)_cohort_ML / (royalty/cost)_cohort_control - 1` | ≥ 30% | Trimestral |
| K6 | % decisiones auto en regimen | `jobs_action_no_override / jobs_action_total` | ≥ 70% Mes 12 Año 2 | Mensual |

### KPI secundarios (operativos)

| ID | Definicion | Target |
|---|---|---|
| K7 | Cobertura inferencia diaria | tracks elegibles cubiertos / total elegibles ≥ 99.5% |
| K8 | Latencia inferencia batch | p95 < 30 min para 5k tracks |
| K9 | Drift trigger time | < 24h desde MAE rolling > 35% hasta auto-retrain |
| K10 | Stability of action | flips KEEP↔HARVEST sin nueva senal en 7d < 5% de tracks |
| K11 | Holdout integrity | 5% holdout permanente sin tocar por ML, auditado mensualmente |

### KPI economicos

| ID | Definicion | Target |
|---|---|---|
| K12 | Costo marginal por unidad LRV decidida | < $0.0005 por dolar de LRV decidido |
| K13 | Ahorro CAPEX produccion | ≥ 20% reduccion gasto en nichos cancelados por niche affinity |
| K14 | Reduccion cost-per-stream tier 1 | ≥ 15% sobre baseline Año 1 (atribuible a mejor asignacion bandit) |

## Definiciones precisas

**Underperformer real** (para K4): un track tiene `underperformer = true` si su `LRV_60d_observed` cae bajo el percentil 25 de su nicho en la cohorte de su mes de release.

**Cohort control** (para K5): 5% holdout permanente decidido humanamente con misma politica que Año 1, congelado al inicio de Año 2. No se le aplica nunca output de modelos.

**Decision auto** (para K6): cualquier transicion de estado de un track (`KEEP_INVESTING`, `HARVEST`, `RETIRE`) ejecutada por el batch nightly sin override humano en las 24h siguientes.

**Catalogo activo** (para K3): tracks con al menos 1 stream en los ultimos 30 dias.

## Anti-objetivos cuantificados

- Si MAE holdout > 35% en 3 retrains consecutivos: rollback a politica humana y reabrir feature engineering.
- Si K10 (stability) > 15%: penalizar funcion de costo del bandit con `||action_t - action_{t-1}||`.
- Si K11 falla auditoria: el modelo se considera contaminado y se invalida la cohort de evaluacion.
