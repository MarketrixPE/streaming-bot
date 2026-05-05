import type {
  Account,
  AnomalyAlert,
  AnomalyDetail,
  AnomalySeverity,
  AnomalyStatus,
  Dsp,
  FeatureContribution,
  Job,
  LiveEvent,
  OverviewKpis,
  StreamsPerDspPoint,
  Tier,
  TimelineEvent,
  Track,
} from "@/types/api";

const mulberry32 = (seed: number): (() => number) => {
  let t = seed >>> 0;
  return () => {
    t = (t + 0x6d2b79f5) >>> 0;
    let r = t;
    r = Math.imul(r ^ (r >>> 15), r | 1);
    r ^= r + Math.imul(r ^ (r >>> 7), r | 61);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
};

const rand = mulberry32(42);

const pick = <T>(arr: readonly T[]): T => {
  const idx = Math.floor(rand() * arr.length);
  return arr[idx] as T;
};

const DSPS = ["spotify", "apple", "amazon", "youtube", "deezer", "tidal"] as const;
const DISTROS = ["distrokid", "tunecore", "cdbaby", "amuse", "onerpm", "ditto"] as const;
const TIERS = ["S", "A", "B", "C", "D"] as const;
const STATUSES = ["live", "pending", "takedown", "paused"] as const;
const ACCOUNT_STATUSES = ["active", "quarantined", "banned", "warming"] as const;
const COUNTRIES = ["US", "MX", "BR", "DE", "ES", "FR", "GB", "JP", "AR", "CO"] as const;
const CITIES: Array<{ city: string; lat: number; lng: number }> = [
  { city: "New York", lat: 40.7128, lng: -74.006 },
  { city: "Mexico City", lat: 19.4326, lng: -99.1332 },
  { city: "Sao Paulo", lat: -23.5505, lng: -46.6333 },
  { city: "Berlin", lat: 52.52, lng: 13.405 },
  { city: "Madrid", lat: 40.4168, lng: -3.7038 },
  { city: "Paris", lat: 48.8566, lng: 2.3522 },
  { city: "London", lat: 51.5074, lng: -0.1278 },
  { city: "Tokyo", lat: 35.6762, lng: 139.6503 },
  { city: "Buenos Aires", lat: -34.6037, lng: -58.3816 },
  { city: "Bogota", lat: 4.711, lng: -74.0721 },
];

const WORKFLOWS = [
  "DailyRun",
  "WarmingWorkflow",
  "CatalogSync",
  "PayoutsRollup",
  "ProxyHealthCheck",
] as const;

const TRACK_TITLES = [
  "Night Drive",
  "Sunset Protocol",
  "Neon Memory",
  "Ghost Harbor",
  "Echo Chamber",
  "Velvet Static",
  "Paper Skies",
  "Midnight Motive",
  "Obsidian Heart",
  "Lumen",
  "Parallel Lines",
  "Glass Bloom",
  "Polar Signal",
  "Cascade",
  "Ion Garden",
];
const ARTISTS = [
  "Lora Vex",
  "Koto Arc",
  "Sable Moon",
  "Noir Atlas",
  "Vela Wren",
  "Orin Kale",
  "Ceres Fade",
  "Mika Pale",
  "Juno Brass",
  "Rho Tern",
];

const makeId = (prefix: string, index: number): string => `${prefix}_${index.toString(36)}`;

export const MOCK_TRACKS: Track[] = Array.from({ length: 64 }, (_, i) => {
  const coverSeed = Math.floor(rand() * 10_000);
  const dspCount = 1 + Math.floor(rand() * DSPS.length);
  const distroCount = 1 + Math.floor(rand() * 3);
  return {
    id: makeId("trk", i),
    coverUrl: `https://picsum.photos/seed/${coverSeed}/80/80`,
    title: TRACK_TITLES[i % TRACK_TITLES.length] ?? "Untitled",
    artist: ARTISTS[i % ARTISTS.length] ?? "Unknown",
    distributors: Array.from(new Set(Array.from({ length: distroCount }, () => pick(DISTROS)))),
    plays30d: Math.floor(500 + rand() * 500_000),
    saveRate: 0.05 + rand() * 0.35,
    skipRate: 0.05 + rand() * 0.4,
    tier: pick(TIERS),
    status: pick(STATUSES),
    dsps: Array.from(new Set(Array.from({ length: dspCount }, () => pick(DSPS)))),
  };
});

export const MOCK_ACCOUNTS: Account[] = Array.from({ length: 90 }, (_, i) => ({
  id: makeId("acc", i),
  label: `acc-${String(i + 1).padStart(4, "0")}@mailbox.test`,
  dsp: pick(DSPS),
  country: pick(COUNTRIES),
  tier: pick(TIERS),
  status: pick(ACCOUNT_STATUSES),
  healthScore: Math.round(20 + rand() * 80),
  lastActionAt: new Date(Date.now() - rand() * 1000 * 60 * 60 * 36).toISOString(),
}));

export const MOCK_JOBS: Job[] = Array.from({ length: 18 }, (_, i) => {
  const status: Job["status"] = (["running", "pending", "completed", "failed"] as const)[
    Math.floor(rand() * 4)
  ] ?? "pending";
  const progress = status === "completed" ? 1 : status === "failed" ? rand() * 0.7 : rand();
  return {
    id: makeId("job", i),
    workflow: WORKFLOWS[i % WORKFLOWS.length] ?? "DailyRun",
    worker: `worker-${(i % 5) + 1}`,
    status,
    progress,
    etaSeconds:
      status === "running" ? Math.round(60 + rand() * 900) : status === "pending" ? null : 0,
    startedAt: new Date(Date.now() - rand() * 1000 * 60 * 120).toISOString(),
  };
});

interface AnomalyClusterSeed {
  geo: string;
  dsp: Dsp;
  tier: Tier;
}

const ANOMALY_CLUSTER_SEEDS: readonly AnomalyClusterSeed[] = [
  { geo: "US", dsp: "spotify", tier: "S" },
  { geo: "MX", dsp: "spotify", tier: "A" },
  { geo: "BR", dsp: "apple", tier: "A" },
  { geo: "DE", dsp: "amazon", tier: "B" },
  { geo: "ES", dsp: "youtube", tier: "B" },
  { geo: "FR", dsp: "spotify", tier: "C" },
  { geo: "GB", dsp: "deezer", tier: "C" },
  { geo: "JP", dsp: "tidal", tier: "D" },
];

interface FeatureSeed {
  name: string;
  displayName: string;
  description: string;
}

const ANOMALY_FEATURE_POOL: readonly FeatureSeed[] = [
  {
    name: "skip_rate_15m",
    displayName: "Skip rate (15m)",
    description: "Porcentaje de skips en ventana móvil de 15 minutos.",
  },
  {
    name: "session_diversity",
    displayName: "Diversidad de sesión",
    description: "Variedad de tracks distintos reproducidos por sesión.",
  },
  {
    name: "ip_reputation",
    displayName: "Reputación IP",
    description: "Score externo de reputación del rango IP utilizado.",
  },
  {
    name: "user_agent_entropy",
    displayName: "Entropía UA",
    description: "Entropía Shannon del User-Agent contra perfil base.",
  },
  {
    name: "play_completion",
    displayName: "Completion rate",
    description: "Porcentaje promedio de completion por reproducción.",
  },
  {
    name: "geo_velocity_kmh",
    displayName: "Velocidad geográfica",
    description: "Distancia entre logins consecutivos sobre tiempo.",
  },
  {
    name: "device_fingerprint_repeats",
    displayName: "Repetición de fingerprint",
    description: "Veces que el fingerprint aparece en cuentas distintas.",
  },
  {
    name: "cookie_age_hours",
    displayName: "Antigüedad de cookie",
    description: "Edad de la cookie de sesión vs perfil esperado.",
  },
];

const SEVERITY_TO_SCORE: Record<AnomalySeverity, [number, number]> = {
  LOW: [0.2, 0.45],
  MEDIUM: [0.45, 0.65],
  HIGH: [0.65, 0.85],
  CRITICAL: [0.85, 0.98],
};

const METRIC_BY_SEVERITY: Record<AnomalySeverity, string> = {
  LOW: "skip_rate_15m",
  MEDIUM: "play_completion",
  HIGH: "ip_reputation",
  CRITICAL: "device_fingerprint_repeats",
};

const SEVERITY_TITLES: Record<AnomalySeverity, string> = {
  LOW: "Indicador suave fuera de rango",
  MEDIUM: "Patrón sospechoso en cohorte",
  HIGH: "Alerta de comportamiento anómalo",
  CRITICAL: "Cuenta probablemente comprometida",
};

const SEVERITY_RANK_FACTOR: Record<AnomalySeverity, number> = {
  LOW: 0.6,
  MEDIUM: 0.85,
  HIGH: 1.0,
  CRITICAL: 1.15,
};

const repeatItems = <T>(value: T, n: number): T[] =>
  Array.from({ length: n }, () => value);

const shuffle = <T>(items: T[], rng: () => number): T[] => {
  const result = [...items];
  for (let i = result.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rng() * (i + 1));
    const a = result[i];
    const b = result[j];
    if (a === undefined || b === undefined) continue;
    result[i] = b;
    result[j] = a;
  }
  return result;
};

const buildSeverityPool = (rng: () => number): AnomalySeverity[] => {
  const pool: AnomalySeverity[] = [
    ...repeatItems<AnomalySeverity>("CRITICAL", 8),
    ...repeatItems<AnomalySeverity>("HIGH", 14),
    ...repeatItems<AnomalySeverity>("MEDIUM", 16),
    ...repeatItems<AnomalySeverity>("LOW", 12),
  ];
  return shuffle(pool, rng);
};

const sampleFeatures = (
  rng: () => number,
  severity: AnomalySeverity,
): FeatureContribution[] => {
  const seeds = shuffle([...ANOMALY_FEATURE_POOL], rng).slice(0, 5);
  const direction = SEVERITY_RANK_FACTOR[severity];
  return seeds.map((seed, idx) => {
    const magnitude = 0.05 + rng() * 0.35;
    const sign = idx === 0 ? 1 : rng() > 0.3 ? 1 : -1;
    const shapValue = Number((sign * magnitude * direction).toFixed(3));
    return {
      name: seed.name,
      displayName: seed.displayName,
      description: seed.description,
      value: Number(rng().toFixed(3)),
      shapValue,
    } satisfies FeatureContribution;
  });
};

const buildAlertSparkline = (
  rng: () => number,
  severity: AnomalySeverity,
): Array<{ t: string; value: number }> => {
  const now = Date.now();
  const baseline =
    severity === "CRITICAL"
      ? 70
      : severity === "HIGH"
        ? 55
        : severity === "MEDIUM"
          ? 40
          : 25;
  const amp =
    severity === "CRITICAL" ? 35 : severity === "HIGH" ? 25 : severity === "MEDIUM" ? 18 : 12;
  return Array.from({ length: 24 }, (_, i) => ({
    t: new Date(now - (23 - i) * 60 * 60 * 1000).toISOString(),
    value: Math.round(baseline + rng() * amp + (i / 23) * (severity === "CRITICAL" ? 18 : 8)),
  }));
};

type TimelineSource = Pick<
  AnomalyAlert,
  "detectedAt" | "status" | "ackAt" | "snoozeUntil" | "retireAt" | "score" | "severity"
>;

const buildTimeline = (alert: TimelineSource): TimelineEvent[] => {
  const events: TimelineEvent[] = [
    {
      kind: "detected",
      at: alert.detectedAt,
      message: `Alerta detectada con score ${alert.score.toFixed(2)} (${alert.severity}).`,
      actor: "anomaly-service",
    },
  ];
  if (alert.ackAt) {
    events.push({
      kind: "acknowledged",
      at: alert.ackAt,
      message: "Operador reconoció la alerta.",
      actor: "ops",
    });
  }
  if (alert.snoozeUntil) {
    events.push({
      kind: "snoozed",
      at: alert.snoozeUntil,
      message: "Alerta silenciada temporalmente.",
      actor: "ops",
    });
  }
  if (alert.retireAt) {
    events.push({
      kind: "retired",
      at: alert.retireAt,
      message: "Cuenta retirada del pool operativo.",
      actor: "ops",
    });
  }
  return events;
};

const stringSeed = (input: string): number => {
  let hash = 2166136261;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
};

const generateAnomalies = (): AnomalyAlert[] => {
  const rng = mulberry32(0xa11cef);
  const severities = buildSeverityPool(rng);
  const total = severities.length;
  const now = Date.now();
  const out: AnomalyAlert[] = [];
  for (let index = 0; index < severities.length; index += 1) {
    const severity = severities[index];
    if (!severity) continue;
    const cluster = ANOMALY_CLUSTER_SEEDS[index % ANOMALY_CLUSTER_SEEDS.length];
    if (!cluster) continue;
    const accountSlot = (index * 7 + 3) % MOCK_ACCOUNTS.length;
    const account = MOCK_ACCOUNTS[accountSlot];
    if (!account) continue;
    const detectedAt = new Date(
      now - Math.floor(rng() * 1000 * 60 * 60 * 22) - 1000 * 60 * 5,
    ).toISOString();
    const features = sampleFeatures(rng, severity);
    const topFeatures = [...features]
      .sort((a, b) => Math.abs(b.shapValue) - Math.abs(a.shapValue))
      .slice(0, 3);
    const range = SEVERITY_TO_SCORE[severity];
    const score = Number((range[0] + rng() * (range[1] - range[0])).toFixed(3));
    const statusRoll = rng();
    const status: AnomalyStatus =
      statusRoll < 0.78
        ? "active"
        : statusRoll < 0.9
          ? "acknowledged"
          : statusRoll < 0.97
            ? "snoozed"
            : "retired";
    const detectedTs = new Date(detectedAt).getTime();
    const ackAt =
      status === "acknowledged"
        ? new Date(detectedTs + 1000 * 60 * (3 + Math.floor(rng() * 25))).toISOString()
        : null;
    const snoozeUntil =
      status === "snoozed"
        ? new Date(detectedTs + 1000 * 60 * 60 * (1 + Math.floor(rng() * 6))).toISOString()
        : null;
    const retireAt =
      status === "retired"
        ? new Date(detectedTs + 1000 * 60 * (10 + Math.floor(rng() * 30))).toISOString()
        : null;
    out.push({
      id: `anom_${index.toString(36)}`,
      accountId: account.id,
      accountLabel: account.label,
      geo: cluster.geo,
      dsp: cluster.dsp,
      tier: cluster.tier,
      metric: METRIC_BY_SEVERITY[severity],
      title: SEVERITY_TITLES[severity],
      description: `${cluster.geo} · ${cluster.dsp} · tier ${cluster.tier} · score ${score.toFixed(
        2,
      )} (${index + 1}/${total}).`,
      severity,
      riskLevel: severity,
      score,
      status,
      detectedAt,
      ackAt,
      retireAt,
      snoozeUntil,
      sparkline: buildAlertSparkline(rng, severity),
      topFeatures,
    });
  }
  return out;
};

export const MOCK_ALERTS: AnomalyAlert[] = generateAnomalies();

export const buildAnomalyDetail = (alert: AnomalyAlert): AnomalyDetail => {
  const rng = mulberry32(stringSeed(alert.id));
  const baseline = sampleFeatures(rng, alert.severity);
  const merged = new Map<string, FeatureContribution>();
  for (const f of [...alert.topFeatures, ...baseline]) {
    if (!merged.has(f.name)) merged.set(f.name, f);
  }
  const features = Array.from(merged.values()).sort(
    (a, b) => Math.abs(b.shapValue) - Math.abs(a.shapValue),
  );
  return {
    ...alert,
    features,
    timeline: buildTimeline(alert),
  };
};

export const MOCK_KPIS: OverviewKpis = {
  streams24h: 182_340,
  streams24hDelta: 0.083,
  activeAccounts: 412,
  activeAccountsDelta: -0.021,
  costPerStream: 0.0021,
  costPerStreamDelta: -0.12,
  revenue7d: 48_210,
  revenue7dDelta: 0.057,
};

export const MOCK_LIVE_EVENTS: LiveEvent[] = Array.from({ length: 48 }, (_, i) => {
  const spot = CITIES[i % CITIES.length];
  if (!spot) {
    return {
      id: makeId("evt", i),
      lat: 0,
      lng: 0,
      dsp: "spotify",
      at: new Date().toISOString(),
      city: "Unknown",
    } satisfies LiveEvent;
  }
  return {
    id: makeId("evt", i),
    lat: spot.lat + (rand() - 0.5) * 1.2,
    lng: spot.lng + (rand() - 0.5) * 1.2,
    dsp: pick(DSPS),
    at: new Date(Date.now() - rand() * 1000 * 60 * 30).toISOString(),
    city: spot.city,
  };
});

export const MOCK_STREAMS_BY_DSP: StreamsPerDspPoint[] = Array.from({ length: 24 }, (_, i) => {
  const now = Date.now();
  const hour = new Date(now - (23 - i) * 60 * 60 * 1000);
  const base = 4000 + Math.floor(rand() * 6000);
  return {
    hour: hour.toISOString(),
    spotify: base + Math.floor(rand() * 2000),
    apple: Math.floor(base * 0.55 + rand() * 1000),
    amazon: Math.floor(base * 0.35 + rand() * 600),
    youtube: Math.floor(base * 0.6 + rand() * 1200),
    deezer: Math.floor(base * 0.18 + rand() * 300),
    tidal: Math.floor(base * 0.12 + rand() * 200),
  };
});
