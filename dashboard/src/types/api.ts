export type Dsp = "spotify" | "apple" | "amazon" | "youtube" | "deezer" | "tidal";

export type Distributor =
  | "distrokid"
  | "tunecore"
  | "cdbaby"
  | "amuse"
  | "onerpm"
  | "ditto";

export type Tier = "S" | "A" | "B" | "C" | "D";

export type TrackStatus = "live" | "pending" | "takedown" | "paused";

export interface Track {
  id: string;
  coverUrl: string;
  title: string;
  artist: string;
  distributors: Distributor[];
  plays30d: number;
  saveRate: number;
  skipRate: number;
  tier: Tier;
  status: TrackStatus;
  dsps: Dsp[];
}

export type AccountStatus = "active" | "quarantined" | "banned" | "warming";

export interface Account {
  id: string;
  label: string;
  dsp: Dsp;
  country: string;
  tier: Tier;
  status: AccountStatus;
  healthScore: number;
  lastActionAt: string;
}

export type JobStatus = "running" | "pending" | "completed" | "failed";

export interface Job {
  id: string;
  workflow: string;
  worker: string;
  status: JobStatus;
  progress: number;
  etaSeconds: number | null;
  startedAt: string;
}

export type {
  AnomalyAlert,
  AnomalyCluster,
  AnomalyDetail,
  AnomalySeverity,
  AnomalyStatus,
  AnomalyTimelineKind,
  FeatureContribution,
  TimelineEvent,
} from "./anomaly";

export interface OverviewKpis {
  streams24h: number;
  streams24hDelta: number;
  activeAccounts: number;
  activeAccountsDelta: number;
  costPerStream: number;
  costPerStreamDelta: number;
  revenue7d: number;
  revenue7dDelta: number;
}

export interface LiveEvent {
  id: string;
  lat: number;
  lng: number;
  dsp: Dsp;
  at: string;
  city: string;
}

export interface StreamsPerDspPoint {
  hour: string;
  spotify: number;
  apple: number;
  amazon: number;
  youtube: number;
  deezer: number;
  tidal: number;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}
