# Año 2 — ML-driven catalog optimization

## Indice

1. [01-thesis-and-kpis.md](./01-thesis-and-kpis.md) — Tesis central, hipotesis verificables, KPIs numericos.
2. [02-data-model.md](./02-data-model.md) — Esquema features, target, fuentes de datos (Postgres + ClickHouse).
3. [03-ml-architecture.md](./03-ml-architecture.md) — Modelos (LRV regressor, Niche affinity, Investment optimizer), pipelines de training, inferencia batch.
4. [04-rollout-plan.md](./04-rollout-plan.md) — 6 sprints (24 semanas) con gates de calidad cuantitativos.
5. [05-risks-mitigations.md](./05-risks-mitigations.md) — Riesgos especificos (feedback loop, drift, saturacion) con mitigaciones medibles.

PoCs ejecutables: [`spikes/year-2/`](../../../spikes/year-2/).

---

## Tesis nuclear

> **Cada track del catalogo tiene un Lifetime Royalty Value (LRV) a 60 dias predecible con error acotado, dado el cohort de senales observadas en los primeros 14 dias post-release. Decidir produccion futura, ramp investment y retiro de tracks basados en `expected_lrv_60d` maximiza ROI marginal del catalogo y hace converger el sistema a un portafolio auto-renovado.**

Concretamente, en Año 1 los humanos deciden:

- Que nichos producir el proximo lote (sleep, lo-fi, ambient, study, kids, white-noise, etc).
- Cuanto streaming budget asignar a cada track en su ramp-up.
- Cuando declarar un track "muerto" y dejar de invertir.

En Año 2 esas tres decisiones se delegan a tres modelos acoplados:

- **LRV regressor**: predice `expected_lrv_60d_cents` y un intervalo de confianza al dia 14 de cada track.
- **Niche affinity**: predice nichos con mayor LRV esperado dado el historico del operador y la saturacion observada.
- **Investment optimizer (contextual bandit)**: asigna streaming budget marginal a tracks vivos (≤14 dias) bajo restriccion de presupuesto diario.

El sistema cierra el loop:

```
[catalog production lote N] -> [release + cohort 14d] -> [LRV regressor] ->
  KEEP_INVESTING / HARVEST / RETIRE -> [Investment optimizer reasigna budget] ->
  [Niche affinity informa lote N+1]
```

## Por que Año 2 y no Año 1

En Año 1 el sistema no tiene suficiente densidad de datos: la granja arranca, el catalogo es pequeño (500 tracks), no hay aun 12 meses de royalty observations confiables, y la operacion humana esta calibrando heuristicas. Año 1 cierra con ~$40k MRR, granja 200-500 modems, pool 10k cuentas, dashboard maduro y entre 12-18 meses de eventos en ClickHouse y royalty observations en Postgres. Esa es la masa critica para entrenar modelos no triviales.

En Año 2 el catalogo crece a 5k+ tracks. Sin automatizacion ML el operador humano se vuelve cuello de botella en las decisiones de produccion / inversion / retiro. El proposito de Año 2 es romper ese cuello.

## Resumen ejecutivo de KPIs Año 2

| KPI | Baseline Año 1 | Target Año 2 | Como se mide |
|---|---|---|---|
| LRV prediction MAE en holdout | n/a | < 25% | MAE absoluto en `lrv_60d_cents` sobre 5% holdout permanente |
| % portafolio renovado / mes | 8-12% (manual) | 30-50% (auto) | tracks publicados ultimo mes / total catalogo activo |
| % underperformers retirados antes Mes 3 | 30-40% (manual, retraso) | ≥ 80% (auto) | tracks con `RETIRE` aplicado antes de dia 90 sobre total underperformers reales |
| ROI lift cohort 2 vs cohort 1 | n/a | ≥ 30% | (royalty cobrado / cost) cohort post-ML vs pre-ML |
| % decisiones automatizadas en regimen | 0% | ≥ 70% Mes 12 Año 2 | jobs `RETIRE` / `KEEP_INVESTING` ejecutados sin override humano |
| Drift trigger time | n/a | ≤ 24h | tiempo desde MAE > umbral hasta auto-retrain disparado |

Cada KPI es atomico, medible diariamente desde ClickHouse + Postgres, y se expone en el dashboard ya existente como una pestaña `Year-2 ML` adicional.

## No-objetivos explicitos

- NO se sustituye el control de takedown / antifraud (eso es Año 1, ya productivo).
- NO se intenta predecir bans de cuentas (ese modelo ya existe en Año 1, `ml-anomaly-prediction`).
- NO se hace generacion de musica AI: el pipeline `ai-catalog-pipeline` de Año 1 sigue siendo input. Año 2 solo decide _que nichos_ priorizar y _que tracks_ retirar.
- NO se prometen mejoras vagas de "calidad". Solo metricas economicas (LRV, ROI) y operativas (% renovado, % retirado a tiempo).
