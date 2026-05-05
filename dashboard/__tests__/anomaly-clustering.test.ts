/**
 * Test plano (sin vitest) para `clusterAnomalies` y helpers.
 *
 * Ejecución manual:
 *   pnpm exec tsx __tests__/anomaly-clustering.test.ts
 *
 * Si no hay tsx disponible, el archivo aún sirve de smoke test bajo
 * `pnpm typecheck` porque ejercita la API pública del módulo.
 */

import assert from "node:assert/strict";

import {
  clusterAnomalies,
  clusterKey,
  filterAlertsByCluster,
  filterAlertsBySeverities,
} from "../src/lib/anomaly-clustering";
import type { AnomalyAlert, AnomalySeverity } from "../src/types/anomaly";

const HOUR_MS = 60 * 60 * 1000;
const NOW = Date.UTC(2026, 0, 15, 12, 0, 0);

const buildAlert = (overrides: Partial<AnomalyAlert> & { id: string }): AnomalyAlert => ({
  accountId: `acc_${overrides.id}`,
  accountLabel: `acc-${overrides.id}@test`,
  geo: "US",
  dsp: "spotify",
  tier: "S",
  metric: "skip_rate_15m",
  title: "Test alert",
  description: "fixture",
  severity: "MEDIUM",
  riskLevel: "MEDIUM",
  score: 0.5,
  status: "active",
  detectedAt: new Date(NOW - HOUR_MS).toISOString(),
  ackAt: null,
  retireAt: null,
  snoozeUntil: null,
  sparkline: [],
  topFeatures: [],
  ...overrides,
});

type TestCase = [name: string, fn: () => void];

const cases: TestCase[] = [
  [
    "clusterKey concatena geo:dsp:tier",
    () => {
      assert.equal(clusterKey("US", "spotify", "S"), "US:spotify:S");
    },
  ],
  [
    "clusterAnomalies agrupa por (geo, dsp, tier)",
    () => {
      const alerts: AnomalyAlert[] = [
        buildAlert({ id: "1", geo: "US", dsp: "spotify", tier: "S" }),
        buildAlert({ id: "2", geo: "US", dsp: "spotify", tier: "S" }),
        buildAlert({ id: "3", geo: "MX", dsp: "spotify", tier: "S" }),
        buildAlert({ id: "4", geo: "US", dsp: "apple", tier: "S" }),
      ];
      const clusters = clusterAnomalies(alerts, { now: NOW });
      assert.equal(clusters.length, 3);
      const us = clusters.find((c) => c.key === "US:spotify:S");
      assert.ok(us);
      assert.equal(us?.count, 2);
      assert.deepEqual(us?.alertIds.sort(), ["1", "2"].sort());
    },
  ],
  [
    "severity del cluster es el máximo de sus alertas",
    () => {
      const alerts: AnomalyAlert[] = [
        buildAlert({ id: "1", severity: "LOW" }),
        buildAlert({ id: "2", severity: "HIGH" }),
        buildAlert({ id: "3", severity: "CRITICAL" }),
      ];
      const [cluster] = clusterAnomalies(alerts, { now: NOW });
      assert.ok(cluster);
      assert.equal(cluster?.severity, "CRITICAL");
      assert.equal(cluster?.countBySeverity.CRITICAL, 1);
      assert.equal(cluster?.countBySeverity.HIGH, 1);
      assert.equal(cluster?.countBySeverity.LOW, 1);
    },
  ],
  [
    "sparkline tiene 24 buckets horarios y suma alertas",
    () => {
      const alerts: AnomalyAlert[] = [
        buildAlert({ id: "1", detectedAt: new Date(NOW - HOUR_MS * 0.5).toISOString() }),
        buildAlert({ id: "2", detectedAt: new Date(NOW - HOUR_MS * 0.5).toISOString() }),
        buildAlert({ id: "3", detectedAt: new Date(NOW - HOUR_MS * 5).toISOString() }),
      ];
      const [cluster] = clusterAnomalies(alerts, { now: NOW });
      assert.ok(cluster);
      assert.equal(cluster?.sparkline.length, 24);
      const total = cluster?.sparkline.reduce((acc, b) => acc + b.value, 0) ?? 0;
      assert.equal(total, 3);
    },
  ],
  [
    "ordena por severidad descendente y luego por count",
    () => {
      const alerts: AnomalyAlert[] = [
        buildAlert({ id: "a1", geo: "US", severity: "MEDIUM" }),
        buildAlert({ id: "a2", geo: "US", severity: "MEDIUM" }),
        buildAlert({ id: "b1", geo: "MX", severity: "CRITICAL" }),
      ];
      const clusters = clusterAnomalies(alerts, { now: NOW });
      assert.equal(clusters[0]?.severity, "CRITICAL");
      assert.equal(clusters[1]?.severity, "MEDIUM");
    },
  ],
  [
    "filterAlertsBySeverities respeta el set vacío como sin filtro",
    () => {
      const alerts: AnomalyAlert[] = [
        buildAlert({ id: "1", severity: "LOW" }),
        buildAlert({ id: "2", severity: "CRITICAL" }),
      ];
      assert.equal(filterAlertsBySeverities(alerts, new Set()).length, 2);
      const onlyCritical = filterAlertsBySeverities(
        alerts,
        new Set<AnomalySeverity>(["CRITICAL"]),
      );
      assert.equal(onlyCritical.length, 1);
      assert.equal(onlyCritical[0]?.id, "2");
    },
  ],
  [
    "filterAlertsByCluster devuelve solo miembros del cluster",
    () => {
      const alerts: AnomalyAlert[] = [
        buildAlert({ id: "1", geo: "US", dsp: "spotify", tier: "S" }),
        buildAlert({ id: "2", geo: "US", dsp: "spotify", tier: "S" }),
        buildAlert({ id: "3", geo: "MX", dsp: "spotify", tier: "S" }),
      ];
      const [cluster] = clusterAnomalies(alerts, { now: NOW });
      assert.ok(cluster);
      const filtered = filterAlertsByCluster(alerts, cluster!);
      assert.equal(filtered.length, 2);
    },
  ],
];

const run = (): void => {
  let failed = 0;
  for (const [name, fn] of cases) {
    try {
      fn();
      console.log(`ok  ${name}`);
    } catch (err) {
      failed += 1;
      console.error(`fail  ${name}`);
      console.error(err);
    }
  }
  if (failed > 0) {
    console.error(`\n${failed} test(s) failed`);
    process.exit(1);
  } else {
    console.log(`\n${cases.length} tests passed`);
  }
};

const argv1 = process.argv[1];
if (argv1 && /anomaly-clustering\.test\.(ts|js|mjs|cjs)$/.test(argv1)) {
  run();
}

export { cases, run };
