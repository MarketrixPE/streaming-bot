import type { Dsp, Tier } from "./api";

export type AnomalySeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type AnomalyStatus = "active" | "acknowledged" | "snoozed" | "retired";

export type AnomalyTimelineKind =
  | "detected"
  | "score_updated"
  | "acknowledged"
  | "snoozed"
  | "retired"
  | "note";

export interface FeatureContribution {
  /** Identificador estable proveniente del modelo (snake_case). */
  name: string;
  /** Etiqueta legible para UI. */
  displayName: string;
  /** Valor crudo del feature en el momento de la observación. */
  value: number;
  /** Aporte SHAP al score final (positivo aumenta riesgo, negativo lo reduce). */
  shapValue: number;
  /** Texto opcional con contexto operativo. */
  description?: string;
}

export interface TimelineEvent {
  kind: AnomalyTimelineKind;
  at: string;
  message: string;
  actor?: string;
}

export interface AnomalyAlert {
  id: string;
  accountId: string;
  accountLabel: string;
  geo: string;
  dsp: Dsp;
  tier: Tier;
  metric: string;
  title: string;
  description: string;
  severity: AnomalySeverity;
  riskLevel: AnomalySeverity;
  score: number;
  status: AnomalyStatus;
  detectedAt: string;
  ackAt: string | null;
  retireAt: string | null;
  snoozeUntil: string | null;
  sparkline: Array<{ t: string; value: number }>;
  topFeatures: FeatureContribution[];
}

export interface AnomalyDetail extends AnomalyAlert {
  features: FeatureContribution[];
  timeline: TimelineEvent[];
}

export interface AnomalyCluster {
  key: string;
  geo: string;
  dsp: Dsp;
  tier: Tier;
  severity: AnomalySeverity;
  count: number;
  countBySeverity: Record<AnomalySeverity, number>;
  alertIds: string[];
  lastDetectedAt: string;
  sparkline: Array<{ t: string; value: number }>;
}

export const SEVERITY_RANK: Record<AnomalySeverity, number> = {
  LOW: 0,
  MEDIUM: 1,
  HIGH: 2,
  CRITICAL: 3,
};

export const SEVERITY_ORDER: readonly AnomalySeverity[] = [
  "LOW",
  "MEDIUM",
  "HIGH",
  "CRITICAL",
] as const;
