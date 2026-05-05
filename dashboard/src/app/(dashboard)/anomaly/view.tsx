"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, CheckCircle2, Pause, ShieldOff } from "lucide-react";

import { AlertDetailDrawer } from "@/components/anomaly/alert-detail-drawer";
import { ClusterGrid } from "@/components/anomaly/cluster-grid";
import { SeverityFilter } from "@/components/anomaly/severity-filter";
import { Topbar } from "@/components/topbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnomalies } from "@/lib/hooks/use-anomalies";
import {
  clusterAnomalies,
  filterAlertsByCluster,
  filterAlertsBySeverities,
} from "@/lib/anomaly-clustering";
import { cn, formatRelative } from "@/lib/utils";
import {
  SEVERITY_RANK,
  type AnomalyAlert,
  type AnomalyCluster,
  type AnomalySeverity,
  type AnomalyStatus,
} from "@/types/anomaly";

const SEVERITY_PILL: Record<AnomalySeverity, string> = {
  LOW: "border-border bg-muted text-muted-foreground",
  MEDIUM: "border-warning/40 bg-warning/15 text-warning",
  HIGH: "border-orange-500/40 bg-orange-500/15 text-orange-500",
  CRITICAL: "border-destructive/40 bg-destructive/15 text-destructive",
};

const STATUS_ICON: Record<
  AnomalyStatus,
  React.ComponentType<{ className?: string }>
> = {
  active: AlertTriangle,
  acknowledged: CheckCircle2,
  snoozed: Pause,
  retired: ShieldOff,
};

const STATUS_TONE: Record<AnomalyStatus, string> = {
  active: "text-destructive",
  acknowledged: "text-success",
  snoozed: "text-warning",
  retired: "text-muted-foreground",
};

interface SummaryStats {
  total: number;
  bySeverity: Record<AnomalySeverity, number>;
  active: number;
}

const buildSummary = (alerts: readonly AnomalyAlert[]): SummaryStats => {
  const bySeverity: Record<AnomalySeverity, number> = {
    LOW: 0,
    MEDIUM: 0,
    HIGH: 0,
    CRITICAL: 0,
  };
  let active = 0;
  for (const a of alerts) {
    bySeverity[a.severity] += 1;
    if (a.status === "active") active += 1;
  }
  return { total: alerts.length, bySeverity, active };
};

export function AnomalyView() {
  const t = useTranslations("anomaly");
  const tSeverity = useTranslations("anomaly.severity");
  const anomalies = useAnomalies();

  const [severityFilter, setSeverityFilter] = React.useState<Set<AnomalySeverity>>(
    () => new Set<AnomalySeverity>(),
  );
  const [selectedClusterKey, setSelectedClusterKey] = React.useState<string | null>(
    null,
  );
  const [selectedAlertId, setSelectedAlertId] = React.useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = React.useState<boolean>(false);

  const allAlerts = React.useMemo<AnomalyAlert[]>(
    () => anomalies.data ?? [],
    [anomalies.data],
  );

  const visibleAlerts = React.useMemo(
    () => filterAlertsBySeverities(allAlerts, severityFilter),
    [allAlerts, severityFilter],
  );

  const clusters = React.useMemo<AnomalyCluster[]>(
    () => clusterAnomalies(visibleAlerts),
    [visibleAlerts],
  );

  React.useEffect(() => {
    if (selectedClusterKey === null) return;
    if (!clusters.some((c) => c.key === selectedClusterKey)) {
      setSelectedClusterKey(null);
    }
  }, [clusters, selectedClusterKey]);

  const selectedCluster = React.useMemo(
    () => clusters.find((c) => c.key === selectedClusterKey) ?? null,
    [clusters, selectedClusterKey],
  );

  const clusterAlerts = React.useMemo<AnomalyAlert[]>(() => {
    if (!selectedCluster) return [];
    return filterAlertsByCluster(visibleAlerts, selectedCluster).sort(
      (a, b) =>
        SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] ||
        new Date(b.detectedAt).getTime() - new Date(a.detectedAt).getTime(),
    );
  }, [selectedCluster, visibleAlerts]);

  const selectedAlert = React.useMemo(
    () => allAlerts.find((a) => a.id === selectedAlertId) ?? null,
    [allAlerts, selectedAlertId],
  );

  const summary = React.useMemo(() => buildSummary(visibleAlerts), [visibleAlerts]);

  const handleClusterSelect = React.useCallback((cluster: AnomalyCluster) => {
    setSelectedClusterKey((prev) => (prev === cluster.key ? null : cluster.key));
  }, []);

  const handleAlertSelect = React.useCallback((alert: AnomalyAlert) => {
    setSelectedAlertId(alert.id);
    setDrawerOpen(true);
  }, []);

  const handleDrawerOpen = React.useCallback((open: boolean) => {
    setDrawerOpen(open);
    if (!open) setSelectedAlertId(null);
  }, []);

  return (
    <>
      <Topbar title={t("title")} subtitle={t("subtitle")} />
      <main className="flex flex-1 flex-col gap-6 p-6">
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryCard label={t("summary.active")} value={summary.active} tone="alert" />
          <SummaryCard
            label={tSeverity("CRITICAL")}
            value={summary.bySeverity.CRITICAL}
            tone="critical"
          />
          <SummaryCard
            label={tSeverity("HIGH")}
            value={summary.bySeverity.HIGH}
            tone="high"
          />
          <SummaryCard
            label={t("summary.clusters")}
            value={clusters.length}
            tone="neutral"
          />
        </section>

        <section className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <SeverityFilter value={severityFilter} onChange={setSeverityFilter} />
          <p className="text-xs text-muted-foreground">
            {t("summary.filtered", {
              filtered: visibleAlerts.length,
              total: allAlerts.length,
            })}
          </p>
        </section>

        {anomalies.isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {Array.from({ length: 6 }).map((_, idx) => (
              <Skeleton key={idx} className="h-40 w-full" />
            ))}
          </div>
        ) : clusters.length === 0 ? (
          <Card>
            <CardContent className="flex h-40 items-center justify-center text-sm text-muted-foreground">
              {t("emptyClusters")}
            </CardContent>
          </Card>
        ) : (
          <ClusterGrid
            clusters={clusters}
            selectedKey={selectedClusterKey}
            onSelect={handleClusterSelect}
          />
        )}

        {selectedCluster ? (
          <Card>
            <CardHeader className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
              <div className="space-y-1">
                <CardTitle>
                  {t("cluster.alertsHeading", { count: clusterAlerts.length })}
                </CardTitle>
                <p className="text-xs text-muted-foreground">
                  {selectedCluster.geo} · {selectedCluster.dsp} · tier{" "}
                  {selectedCluster.tier}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedClusterKey(null)}
                className="self-start text-xs text-muted-foreground underline-offset-2 hover:underline"
              >
                {t("cluster.clear")}
              </button>
            </CardHeader>
            <CardContent>
              {clusterAlerts.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("emptyAlerts")}</p>
              ) : (
                <ul className="divide-y divide-border">
                  {clusterAlerts.map((alert) => {
                    const StatusIcon = STATUS_ICON[alert.status];
                    return (
                      <li key={alert.id}>
                        <button
                          type="button"
                          onClick={() => handleAlertSelect(alert)}
                          className="flex w-full items-center gap-3 px-1 py-3 text-left transition hover:bg-accent/40"
                        >
                          <span
                            className={cn(
                              "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide",
                              SEVERITY_PILL[alert.severity],
                            )}
                          >
                            {tSeverity(alert.severity)}
                          </span>
                          <div className="min-w-0 flex-1 space-y-0.5">
                            <p className="truncate text-sm font-medium">
                              {alert.title}
                            </p>
                            <p className="truncate text-xs text-muted-foreground">
                              <span className="font-mono">{alert.accountLabel}</span>
                              {" · "}
                              {alert.metric}
                              {" · "}
                              {formatRelative(alert.detectedAt)}
                            </p>
                          </div>
                          <span className="hidden text-right text-xs font-mono tabular-nums text-muted-foreground sm:inline">
                            {alert.score.toFixed(2)}
                          </span>
                          <StatusIcon
                            className={cn("h-4 w-4 shrink-0", STATUS_TONE[alert.status])}
                            aria-hidden
                          />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </CardContent>
          </Card>
        ) : null}
      </main>

      <AlertDetailDrawer
        alert={selectedAlert}
        open={drawerOpen}
        onOpenChange={handleDrawerOpen}
      />
    </>
  );
}

interface SummaryCardProps {
  label: string;
  value: number;
  tone: "alert" | "critical" | "high" | "neutral";
}

const TONE_CLASSES: Record<SummaryCardProps["tone"], string> = {
  alert: "border-border",
  critical: "border-destructive/30",
  high: "border-orange-500/30",
  neutral: "border-border",
};

const TONE_VALUE: Record<SummaryCardProps["tone"], string> = {
  alert: "text-foreground",
  critical: "text-destructive",
  high: "text-orange-500",
  neutral: "text-foreground",
};

function SummaryCard({ label, value, tone }: SummaryCardProps) {
  return (
    <Card className={cn("border", TONE_CLASSES[tone])}>
      <CardContent className="flex flex-col gap-1 p-4">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        <span
          className={cn("text-2xl font-semibold tabular-nums", TONE_VALUE[tone])}
        >
          {value}
        </span>
      </CardContent>
    </Card>
  );
}
