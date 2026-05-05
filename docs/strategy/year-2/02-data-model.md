# 02 — Modelo de datos

## Objetivo

Definir un esquema unico de features + target consumible por los 3 modelos (LRV regressor, Niche affinity, Investment optimizer), construido por queries sobre las fuentes existentes en Año 1: Postgres (catalogo, tracks, costs) y ClickHouse (eventos de stream + royalty observations).

## Fuentes de datos (existentes Año 1)

| Capa | Tabla | Tipo | Notas |
|---|---|---|---|
| Postgres | `tracks` | dimension | id, niche, distros, release_date, retired_at, production_cost_cents |
| Postgres | `track_dsps` | bridge | track_id, dsp ('spotify','soundcloud',...), external_id, published_at |
| Postgres | `track_costs` | hechos lentos | track_id, cost_type ('production'|'distribution'|'streaming_invest'), amount_cents, created_at |
| Postgres | `niches` | dimension | code, lifecycle_stage, expected_payout_tier |
| Postgres | `accounts` | dimension | id, country, premium_tier, retired_at |
| ClickHouse | `events.stream_events` | hot path | track_id, account_id, dsp, country, ts, duration_s, event_type ('play','save','skip','queue','playlist_add'), is_premium_listener, session_id |
| ClickHouse | `events.royalty_observations` | hechos diarios | track_id, dsp, distro, country, ts_day, amount_cents, currency, raw_streams_reported, conversion_rate |
| ClickHouse | `events.investment_ledger` | hechos | track_id, ts_day, streaming_cost_cents, target_geo |

Estas tablas existen al cierre de Año 1. No requieren cambios disruptivos para Año 2: agregamos vistas materializadas adicionales y un ETL feature-mart.

## Tabla feature mart (nueva — Año 2)

Localizacion: ClickHouse base `ml_features`. Replicada bajo demanda a parquet en MinIO para training offline.

```sql
CREATE TABLE ml_features.track_cohort_14d
(
    track_id            UUID,
    feature_snapshot_at DateTime,             -- siempre release_date + 14d
    niche               LowCardinality(String),
    dsps_published      Array(LowCardinality(String)),
    distros             Array(LowCardinality(String)),

    -- Cost features
    production_cost_cents          Int64,
    distribution_cost_cents        Int64,
    streaming_invest_d0_d14_cents  Int64,

    -- Daily play volume (d1..d14)
    plays_d1   UInt64, plays_d2   UInt64, plays_d3   UInt64, plays_d4   UInt64,
    plays_d5   UInt64, plays_d6   UInt64, plays_d7   UInt64, plays_d8   UInt64,
    plays_d9   UInt64, plays_d10  UInt64, plays_d11  UInt64, plays_d12  UInt64,
    plays_d13  UInt64, plays_d14  UInt64,

    -- Aggregate behavioral signals
    save_rate_d7    Float32,
    save_rate_d14   Float32,
    skip_rate_d7    Float32,
    skip_rate_d14   Float32,
    queue_rate_d14  Float32,
    completion_rate_d14 Float32,

    -- Geo distribution (top-5 countries by play, weights summing to 1.0)
    geo_top5_codes  Array(LowCardinality(String)),
    geo_top5_weights Array(Float32),

    -- Premium ratio
    ratio_premium_listeners_d14 Float32,

    -- Discovery surface
    playlist_adds_count_d14 UInt32,
    organic_share_estimate_d14 Float32,  -- 1 - share atribuible a granja

    -- Catalog context
    same_niche_releases_last_30d UInt32,
    niche_saturation_score Float32,

    -- Derived velocity
    save_velocity_d3_to_d7 Float32,
    play_velocity_d7_to_d14 Float32,

    -- Operator context
    operator_track_index_in_month UInt32,    -- numero ordinal del track en su lote mensual

    PRIMARY KEY (track_id)
)
ENGINE = ReplacingMergeTree(feature_snapshot_at)
ORDER BY (track_id);
```

## Tabla target

```sql
CREATE TABLE ml_features.track_lrv_target
(
    track_id          UUID,
    snapshot_at       DateTime,                -- release_date + 60d
    lrv_60d_cents     Int64,                   -- sum royalty d15..d60
    lrv_60d_premium_cents  Int64,
    lrv_60d_per_dsp   Map(String, Int64),
    royalty_observation_count UInt32,
    is_holdout_track  UInt8,                   -- 1 si pertenece al 5% intocable
    cohort_release_month  Date,
    PRIMARY KEY (track_id)
)
ENGINE = ReplacingMergeTree(snapshot_at)
ORDER BY (track_id);
```

`lrv_60d_cents` se materializa exactamente a `release_date + 60d + delay_royalty_pipeline` (tipico: + 75d total). Hasta entonces el target esta en estado `pending`.

## Vista de joining para training

```sql
CREATE VIEW ml_features.training_dataset_v1 AS
SELECT
    f.*,
    t.lrv_60d_cents       AS target_lrv_60d_cents,
    t.lrv_60d_premium_cents AS target_lrv_60d_premium_cents,
    t.is_holdout_track    AS holdout_flag,
    t.cohort_release_month
FROM ml_features.track_cohort_14d f
INNER JOIN ml_features.track_lrv_target t USING (track_id)
WHERE t.snapshot_at < now() - INTERVAL 7 DAY;  -- aseguramos liquidacion estable
```

## ETL pipelines (Temporal workflows)

Todo orquestado en el cluster Temporal ya existente. Activities reutilizan el codigo de `infrastructure/persistence/` y un nuevo paquete `infrastructure/ml_features/`.

| Workflow | Schedule | Activities |
|---|---|---|
| `BuildCohort14dFeatures` | diario 04:00 UTC | (1) seleccionar tracks con `release_date = today - 14d`, (2) materializar features desde stream_events / investment_ledger, (3) escribir a `track_cohort_14d`, (4) emitir metric `cohort14d_built_count` |
| `MaterializeLrvTarget` | diario 06:00 UTC | (1) tracks con `release_date = today - 75d`, (2) sum royalties d15..d60 desde `royalty_observations`, (3) marcar holdout segun hash determinista del track_id, (4) escribir target |
| `BackfillCohort14dFeatures` | one-shot Sprint 1 | recorre 12 meses historicos, idempotente sobre `track_id` |
| `ExportTrainingParquet` | semanal | dump `training_dataset_v1` a `s3://ml-features/training/{week}.parquet` |

## Determinacion de holdout permanente

```python
def is_holdout(track_id: UUID, salt: str = "y2-ml-holdout-2027") -> bool:
    h = hashlib.blake2b(track_id.bytes + salt.encode(), digest_size=8).digest()
    bucket = int.from_bytes(h, "big") % 1000
    return bucket < 50  # 5%
```

Este criterio:

- Es deterministico (no muta entre retrains).
- Independiente de cualquier feature predictiva (no introduce sesgo).
- Auditable: cualquier engineer puede recomputar el set en 1 linea.

## Normalizacion y calidad de datos

| Regla | Mecanismo |
|---|---|
| Tracks con < 50 plays totales d1-d14 | excluidos de training (`min_volume_filter`) |
| Tracks de holdout | NUNCA aparecen en training, validacion ni hyperparam tuning |
| Tracks con `retired_at < release_date + 14d` | excluidos (sesgo supervivencia inverso) |
| Outliers LRV > P99.5 | winsorization a P99.5 (configurable) |
| Missing geo (proxy fail) | feature `geo_unknown_share` que captura el ratio |
| Currency normalization | todos los amounts a cents USD via tabla `fx_rates_daily` con fecha-de-pago |

## Versionado del schema

`ml_features.track_cohort_14d` y `ml_features.track_lrv_target` se versionan via sufijo `_vN`. Cuando se introduce nueva feature:

1. Crear `track_cohort_14d_v2` con la columna agregada.
2. Backfill paralelo.
3. Promover en feature config tras 1 ciclo training-validacion.
4. v1 conservada 90 dias, despues drop.

El feature config vive en `application/ml/feature_spec.yaml` con campos: `name`, `dtype`, `nullability`, `since_version`, `transform`. Esto evita acoplar codigo de modelo a SQL.

## Lineage y observabilidad

- Metricas Prometheus por workflow: `feature_mart_rows_built`, `feature_mart_lag_seconds`, `target_materialized_rows`.
- Loki collecta logs estructurados de cada activity con `track_id` + `workflow_id`.
- Auditoria del holdout en Postgres: tabla `ml_audit.holdout_proof` con hash mensual del set para detectar fugas.
