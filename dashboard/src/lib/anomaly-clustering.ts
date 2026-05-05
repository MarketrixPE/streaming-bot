import {
  SEVERITY_ORDER,
  SEVERITY_RANK,
  type AnomalyAlert,
  type AnomalyCluster,
  type AnomalySeverity,
} from "@/types/anomaly";

const HOUR_MS = 60 * 60 * 1000;

export const clusterKey = (geo: string, dsp: string, tier: string): string =>
  `${geo}:${dsp}:${tier}`;

export interface ClusterOptions {
  /** Tamaño del bucket en milisegundos (default: 1 hora). */
  bucketMs?: number;
  /** Cantidad de buckets para la sparkline (default: 24). */
  buckets?: number;
  /** Tiempo de referencia. Permite tests deterministas. */
  now?: number;
}

const buildSparkline = (
  alerts: readonly AnomalyAlert[],
  bucketMs: number,
  buckets: number,
  now: number,
): Array<{ t: string; value: number }> => {
  const start = now - buckets * bucketMs;
  const series: Array<{ t: string; value: number }> = [];
  for (let i = 0; i < buckets; i += 1) {
    series.push({
      t: new Date(start + (i + 1) * bucketMs).toISOString(),
      value: 0,
    });
  }
  for (const alert of alerts) {
    const ts = new Date(alert.detectedAt).getTime();
    if (!Number.isFinite(ts)) continue;
    const idx = Math.floor((ts - start) / bucketMs);
    if (idx < 0 || idx >= buckets) continue;
    const bucket = series[idx];
    if (bucket) bucket.value += 1;
  }
  return series;
};

const toSeverityFromRank = (rank: number): AnomalySeverity => {
  const safe = Math.max(0, Math.min(SEVERITY_ORDER.length - 1, rank));
  return SEVERITY_ORDER[safe] ?? "LOW";
};

/**
 * Agrupa alertas por (geo, dsp, tier).
 * La severidad del cluster es el máximo entre sus alertas.
 * El sort por defecto: severidad desc, count desc.
 */
export function clusterAnomalies(
  alerts: readonly AnomalyAlert[],
  options: ClusterOptions = {},
): AnomalyCluster[] {
  const bucketMs = options.bucketMs ?? HOUR_MS;
  const buckets = options.buckets ?? 24;
  const now = options.now ?? Date.now();

  const groups = new Map<string, AnomalyAlert[]>();
  for (const alert of alerts) {
    const key = clusterKey(alert.geo, alert.dsp, alert.tier);
    const list = groups.get(key);
    if (list) list.push(alert);
    else groups.set(key, [alert]);
  }

  const clusters: AnomalyCluster[] = [];
  for (const [key, members] of groups) {
    const head = members[0];
    if (!head) continue;
    const counts: Record<AnomalySeverity, number> = {
      LOW: 0,
      MEDIUM: 0,
      HIGH: 0,
      CRITICAL: 0,
    };
    let maxRank = 0;
    let lastTs = 0;
    for (const m of members) {
      counts[m.severity] += 1;
      const r = SEVERITY_RANK[m.severity];
      if (r > maxRank) maxRank = r;
      const ts = new Date(m.detectedAt).getTime();
      if (Number.isFinite(ts) && ts > lastTs) lastTs = ts;
    }
    clusters.push({
      key,
      geo: head.geo,
      dsp: head.dsp,
      tier: head.tier,
      severity: toSeverityFromRank(maxRank),
      count: members.length,
      countBySeverity: counts,
      alertIds: members.map((m) => m.id),
      lastDetectedAt: new Date(lastTs).toISOString(),
      sparkline: buildSparkline(members, bucketMs, buckets, now),
    });
  }

  clusters.sort((a, b) => {
    const sevDiff = SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity];
    if (sevDiff !== 0) return sevDiff;
    if (b.count !== a.count) return b.count - a.count;
    return a.key.localeCompare(b.key);
  });

  return clusters;
}

export const filterAlertsByCluster = (
  alerts: readonly AnomalyAlert[],
  cluster: AnomalyCluster,
): AnomalyAlert[] =>
  alerts.filter(
    (a) => a.geo === cluster.geo && a.dsp === cluster.dsp && a.tier === cluster.tier,
  );

export const filterAlertsBySeverities = (
  alerts: readonly AnomalyAlert[],
  severities: ReadonlySet<AnomalySeverity>,
): AnomalyAlert[] => {
  if (severities.size === 0) return [...alerts];
  return alerts.filter((a) => severities.has(a.severity));
};
