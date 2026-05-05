"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import { ArrowRight } from "lucide-react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Sparkline } from "@/components/charts/sparkline";
import { cn, formatRelative } from "@/lib/utils";
import { type AnomalyCluster, type AnomalySeverity } from "@/types/anomaly";

interface ClusterCardProps {
  cluster: AnomalyCluster;
  selected?: boolean;
  onSelect: (cluster: AnomalyCluster) => void;
  className?: string;
}

const SEVERITY_PILL: Record<AnomalySeverity, string> = {
  LOW: "border-border bg-muted text-muted-foreground",
  MEDIUM: "border-warning/40 bg-warning/15 text-warning",
  HIGH: "border-orange-500/40 bg-orange-500/15 text-orange-500",
  CRITICAL: "border-destructive/40 bg-destructive/15 text-destructive",
};

const SEVERITY_HSL: Record<AnomalySeverity, string> = {
  LOW: "215 16% 47%",
  MEDIUM: "38 92% 55%",
  HIGH: "24 92% 55%",
  CRITICAL: "0 72% 51%",
};

export function ClusterCard({
  cluster,
  selected = false,
  onSelect,
  className,
}: ClusterCardProps) {
  const t = useTranslations("anomaly");
  const tSeverity = useTranslations("anomaly.severity");
  return (
    <button
      type="button"
      onClick={() => onSelect(cluster)}
      aria-pressed={selected}
      className={cn(
        "group block w-full rounded-xl text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      <Card
        className={cn(
          "transition group-hover:border-primary/40",
          selected && "border-primary ring-1 ring-primary",
        )}
      >
        <CardHeader className="flex flex-row items-start justify-between gap-3 p-4">
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide",
                  SEVERITY_PILL[cluster.severity],
                )}
              >
                {tSeverity(cluster.severity)}
              </span>
              <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {t("cluster.title")}
              </span>
            </div>
            <p className="truncate text-sm font-semibold">
              {cluster.geo} · {cluster.dsp} · tier {cluster.tier}
            </p>
            <p className="text-xs text-muted-foreground">
              {t("cluster.lastSeen")} {formatRelative(cluster.lastDetectedAt)}
            </p>
          </div>
          <div className="flex flex-col items-end gap-1">
            <span className="text-2xl font-semibold leading-none tabular-nums">
              {cluster.count}
            </span>
            <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
              {t("cluster.alerts")}
            </span>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 p-4 pt-0">
          <Sparkline
            data={cluster.sparkline}
            colorVar={SEVERITY_HSL[cluster.severity]}
            height={56}
          />
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span>
              {t("cluster.criticalCount", { count: cluster.countBySeverity.CRITICAL })}
              {" · "}
              {t("cluster.highCount", { count: cluster.countBySeverity.HIGH })}
            </span>
            <span className="inline-flex items-center gap-1 font-medium text-foreground/80 group-hover:text-primary">
              {t("cluster.openDetail")}
              <ArrowRight className="h-3 w-3" aria-hidden />
            </span>
          </div>
        </CardContent>
      </Card>
    </button>
  );
}
