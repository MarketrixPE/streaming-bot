# 03 — Arquitectura ML

## Vista de bloques

```
                    +-------------------------------+
                    |   feature mart (ClickHouse)   |
                    |   ml_features.track_cohort_14d|
                    |   ml_features.track_lrv_target|
                    +---------------+---------------+
                                    |
            +-----------------------+-----------------------+
            |                       |                       |
+-----------v-----------+ +---------v---------+ +-----------v-----------+
|  LRV regressor v1     | | Niche affinity v1 | | Contextual bandit v1  |
|  LightGBM quantile    | | Multi-label clf   | | LinUCB / Thompson     |
|  preds: p10/p50/p90   | | targets: niches   | | actions: budget %     |
+-----------+-----------+ +---------+---------+ +-----------+-----------+
            |                       |                       |
            +----------+------------+-----------------------+
                       |
            +----------v---------+
            |  Decision service  |   <- batch nightly
            |  (Python, Temporal)|
            +----------+---------+
                       |
            +----------v---------+
            |  tracks.action     |   KEEP_INVESTING / HARVEST / RETIRE
            |  tracks.expected_  |   expected_lrv_60d_cents
            |  lrv_60d_cents     |
            |  + budget_alloc    |
            +--------------------+
```

## Modelo 1 — LRV regressor

### Algoritmo
LightGBM con loss `quantile` entrenado tres veces para `p10`, `p50` y `p90`.

Razon: nos importan no solo el punto sino el rango (`p90 - p10`) para que el bandit y la decision service tengan incertidumbre explicita. Tracks con intervalo ancho son candidatos a "wait & see"; tracks con intervalo estrecho permiten decisiones decisivas.

### Inputs
Vector de features de `ml_features.track_cohort_14d` (~ 60 columnas tras one-hot del niche / DSPs / distros + arrays de plays diarios + agregados).

### Output
- `expected_lrv_60d_cents_p10`
- `expected_lrv_60d_cents_p50`
- `expected_lrv_60d_cents_p90`

### Hyperparametros base (a tunear)
```yaml
n_estimators: 800
learning_rate: 0.03
num_leaves: 64
min_child_samples: 50
feature_fraction: 0.8
bagging_fraction: 0.8
bagging_freq: 5
reg_alpha: 0.1
reg_lambda: 0.1
objective: quantile
alphas: [0.1, 0.5, 0.9]
```

Tuning con Optuna (60 trials, time-based CV con 5 folds rolling).

### Loss y metrica
Loss: pinball (quantile). Metrica de evaluacion principal: MAE relativo de `p50` sobre holdout. Calibracion verificada via interval coverage: la fraccion observada de `actual ∈ [p10, p90]` debe estar en `[0.78, 0.82]`.

## Modelo 2 — Niche affinity

### Algoritmo
Clasificador multi-label LightGBM (`objective=binary` por nicho, OneVsRest) con calibracion isotonic.

Razon de no usar redes: 30-50 nichos, dataset moderado (decenas de miles de tracks histroicos), interpretabilidad valiosa, training rapido (< 5 min).

### Inputs
- Historico operador: agregados rolling 30/60/90 dias por nicho (LRV total, num tracks, success rate definido como `LRV >= percentil 60 nicho`).
- Saturacion observada: `same_niche_releases_last_30d`, `niche_saturation_score` (precomputado en feature mart).
- Senales externas: tendencias de busqueda, snapshot mensual de top-100 playlists publicas por nicho (scraping ya existente para algunos nichos en Año 1).

### Output
Top-K (K=10) nichos con `expected_lrv_per_track_cents` predicho y `confidence_score`.

### Uso operativo
La salida es un ranking; el ai-catalog-pipeline (existente Año 1) lee este ranking para decidir el lote de produccion del proximo mes. El humano puede vetar nichos (compliance, branding) pero no agregar manualmente sin pasar por el modelo.

## Modelo 3 — Investment optimizer (contextual bandit)

### Algoritmo
LinUCB contextual bandit con reward = LRV marginal observado a 30 dias de la asignacion de budget.

Razon: el problema es secuencial (cada noche decidimos cuanto budget asignar a cada track vivo) bajo restriccion `sum(budget_t) ≤ B_diario`. Contextual bandit explota uso historico y explora suficientemente. RL pleno (PPO) es overkill para horizon corto y dataset moderado.

### Estado / contexto por track
- Vector de cohort_14d features.
- Predicciones del LRV regressor (p10/p50/p90).
- Edad del track (dias desde release).
- Cumulative invest a la fecha.
- LRV observado parcial.

### Acciones
Discretizacion del budget en buckets: `[0, 5, 10, 25, 50, 100, 200] $/track/dia`. Bucket 0 = HARVEST silencioso; budget alto = ramp.

### Reward
`reward = delta_LRV_30d - cost_streaming_30d - lambda * action_volatility`.

`action_volatility` penaliza saltos bruscos para evitar wash-trading entre acciones (KPI K10).

### Restriccion de presupuesto
Resuelto por knapsack-greedy sobre los UCB scores: ordenar tracks por `(UCB_score / cost_action)`, asignar hasta agotar `B_diario`.

### Exploracion
Coeficiente UCB `alpha = 1.5` decreciente a `0.5` durante 60 dias post-deploy. Despues fijo en `0.5`.

### Cold-start
Tracks con < 7 dias de historia: usar policy heurística (LRV regressor p50 + bucket `25` por defecto) hasta tener cohort completo.

## Pipeline de training

```
weekly cron (Temporal, lunes 02:00 UTC)
   |
   v
[ExportTrainingParquet] -> S3
   |
   v
[ContainerJob: ml-trainer:latest]
   - load parquet
   - filter holdout (is_holdout=1) -> nunca tocado
   - time-based split: oldest 80% train, next 10% val, latest 10% test (sin holdout)
   - hyperparam search Optuna 60 trials
   - train LRV p10/p50/p90
   - train Niche affinity
   - evaluate over holdout: MAE, P90, coverage, lift simulated
   - if MAE_holdout < 25% AND coverage in [0.78, 0.82]:
        publish artifacts to model registry
   - else:
        emit alert, do not promote
```

## Inferencia batch (nightly)

Workflow Temporal `RunNightlyDecisionBatch`, schedule 03:00 UTC.

Activities:
1. `LoadActiveTracks`: tracks con `age_days <= 14` o `action == KEEP_INVESTING`.
2. `LoadCohortFeatures`: features de cada uno desde `track_cohort_14d` (snapshot mas reciente).
3. `PredictLRV`: LightGBM regressor en batch (~5k tracks, < 30s).
4. `ScoreActions`:
   - Si `age_days < 14`: action = `KEEP_INVESTING` (no decision aun).
   - Si `age_days >= 14` y `expected_lrv_60d_p50 < production_cost + distribution_cost + threshold_HARVEST`: action = `RETIRE`.
   - Si `expected_lrv_60d_p50 >= breakeven * 1.5`: action = `KEEP_INVESTING`.
   - Else: action = `HARVEST` (mantener publicado, no invertir streaming).
5. `RunBandit`: para tracks con `action == KEEP_INVESTING`, asignar budget bucket via LinUCB respetando knapsack `B_diario`.
6. `WriteDecisions`: actualizar Postgres `tracks.action`, `tracks.expected_lrv_60d_cents_p50`, `tracks.budget_bucket_today`.
7. `EmitAuditEvent`: cada decision se loggea con `model_version`, `feature_hash`, `confidence_band`.

## Model registry

Self-hosted MLflow en infra existente (Hetzner) o, alternativa minimalista, joblib + metadata JSON en MinIO con manifiesto:

```json
{
  "model_id": "lrv_p50_v3",
  "trained_at": "2027-03-15T02:14:00Z",
  "training_data_hash": "sha256:...",
  "feature_spec_version": "v2",
  "metrics_holdout": {"mae_relative": 0.221, "p90_relative": 0.47, "coverage_p10_p90": 0.79},
  "hyperparams": {...},
  "promoted": true,
  "promoted_by": "auto",
  "promotion_gate_passed": ["mae<0.25", "coverage_in_band"]
}
```

Cada inferencia escribe `model_id` consumido en columna `decisions.model_id` para reproducibilidad.

## Monitoreo en produccion (no opcional)

| Metrica | Source | Alerta |
|---|---|---|
| `lrv_pred_mae_rolling_7d` | Prometheus | > 0.30 → warning, > 0.35 → trigger retrain |
| `lrv_pred_coverage_rolling_30d` | Prometheus | fuera de [0.75, 0.85] |
| `bandit_regret_rolling_30d` | Prometheus | > umbral → revisar exploration |
| `holdout_set_hash_drift` | cron audit | cambio inesperado → bloqueo modelo |
| `feature_mart_lag_seconds` | Prometheus | > 6h → alarmar |
| `decisions_diverging_from_humans_pct` | Postgres view | spikes > 30% en 1 dia → revision manual |
| `tracks_action_flip_rate_7d` | Postgres view | > 15% → ajustar `action_volatility` lambda |

## Stack y tooling

- Lenguaje: Python 3.12.
- Librerias: `lightgbm`, `scikit-learn`, `optuna`, `pandas`, `pyarrow`, `clickhouse-connect`, `psycopg[binary]`, `mlflow` (opcional), `pydantic` v2.
- Compute training: Hetzner EX (mismo cluster Año 1) con AMD Ryzen 9 7950X3D, 128GB RAM, NVMe. GPU NO requerido (LightGBM es CPU-bound).
- Compute inferencia: misma infra. Inferencia 5k tracks en una iteracion < 30s.
- Orquestacion: Temporal (existente Año 1).
- Persistencia: ClickHouse (features, eventos), Postgres (decisiones, audit).

## Limites de scope explicitos

- NO usamos LLMs como predictores (son no-deterministicos, caros y aportan poco sobre datos tabulares).
- NO entrenamos modelos por DSP separados Año 2 (ROI marginal bajo, complica deployment). Año 3 reevaluar.
- NO automatizamos decisiones de catalogo "creativas" (titulos, art covers). Solo cantidad y nicho.
- NO hacemos active learning explicito; el bandit ya cubre exploration.
