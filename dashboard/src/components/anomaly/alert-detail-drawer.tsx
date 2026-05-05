"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import { CheckCircle2, Pause, ShieldOff } from "lucide-react";

import {
  FeatureImpactBar,
  computeMaxAbsShap,
} from "@/components/anomaly/feature-impact-bar";
import { Timeline } from "@/components/anomaly/timeline";
import { Sparkline } from "@/components/charts/sparkline";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useAcknowledgeAnomaly,
  useAnomalyDetails,
  useRetireAccount,
  useSnoozeAnomaly,
} from "@/lib/hooks/use-anomalies";
import { cn, formatRelative } from "@/lib/utils";
import type { AnomalyAlert, AnomalySeverity } from "@/types/anomaly";

interface AlertDetailDrawerProps {
  alert: AnomalyAlert | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const SEVERITY_BADGE: Record<AnomalySeverity, string> = {
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

const DEFAULT_SNOOZE_HOURS = 4;

export function AlertDetailDrawer({
  alert,
  open,
  onOpenChange,
}: AlertDetailDrawerProps) {
  const t = useTranslations("anomaly");
  const tStatus = useTranslations("anomaly.status");
  const tSeverity = useTranslations("anomaly.severity");

  const accountId = alert?.accountId ?? null;
  const details = useAnomalyDetails(accountId, { enabled: open });

  const ack = useAcknowledgeAnomaly();
  const retire = useRetireAccount();
  const snooze = useSnoozeAnomaly();

  React.useEffect(() => {
    if (!open) {
      ack.reset();
      retire.reset();
      snooze.reset();
    }
  }, [open, ack, retire, snooze]);

  const fallbackTitle = alert?.title ?? t("emptyDetail");
  const fallbackSubtitle = alert
    ? `${alert.geo} · ${alert.dsp} · tier ${alert.tier}`
    : undefined;

  const canAck = alert ? alert.status === "active" : false;
  const canSnooze = alert
    ? alert.status === "active" || alert.status === "acknowledged"
    : false;
  const canRetire = alert ? alert.status !== "retired" : false;

  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      side="right"
      title={fallbackTitle}
      description={fallbackSubtitle}
    >
      {alert ? (
        <div className="space-y-6">
          <section className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide",
                  SEVERITY_BADGE[alert.severity],
                )}
              >
                {tSeverity(alert.severity)}
              </span>
              <Badge variant="outline" className="font-mono">
                {alert.accountLabel}
              </Badge>
              <Badge variant="outline" className="capitalize">
                {tStatus(alert.status)}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">{alert.description}</p>
            <div className="grid grid-cols-3 gap-3 rounded-lg border bg-muted/30 p-3 text-xs">
              <KeyValue label={t("alert.score")} value={alert.score.toFixed(2)} />
              <KeyValue label={t("alert.metric")} value={alert.metric} mono />
              <KeyValue
                label={t("alert.detectedAt")}
                value={formatRelative(alert.detectedAt)}
              />
            </div>
            <div className="grid grid-cols-3 gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={!canAck || ack.isPending}
                onClick={() => ack.mutate(alert.id)}
              >
                <CheckCircle2 className="h-4 w-4" aria-hidden />
                {t("alert.ack")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!canSnooze || snooze.isPending}
                onClick={() =>
                  snooze.mutate({ id: alert.id, hours: DEFAULT_SNOOZE_HOURS })
                }
              >
                <Pause className="h-4 w-4" aria-hidden />
                {t("alert.snooze")}
              </Button>
              <Button
                variant="destructive"
                size="sm"
                disabled={!canRetire || retire.isPending}
                onClick={() => retire.mutate(alert.accountId)}
              >
                <ShieldOff className="h-4 w-4" aria-hidden />
                {t("alert.retire")}
              </Button>
            </div>
          </section>

          <section className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {t("alert.trend")}
            </h3>
            <Sparkline
              data={alert.sparkline}
              colorVar={SEVERITY_HSL[alert.severity]}
              height={96}
            />
          </section>

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("feature.title")}
              </h3>
              <span className="text-[11px] text-muted-foreground">
                {t("feature.subtitle")}
              </span>
            </div>
            {details.isLoading && !details.data ? (
              <div className="space-y-3">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : (
              (() => {
                const features = details.data?.features ?? alert.topFeatures;
                const maxAbsShap = computeMaxAbsShap(features);
                if (features.length === 0) {
                  return (
                    <p className="text-xs text-muted-foreground">
                      {t("feature.empty")}
                    </p>
                  );
                }
                return (
                  <ul className="space-y-3">
                    {features.slice(0, 3).map((feature) => (
                      <li key={feature.name}>
                        <FeatureImpactBar
                          feature={feature}
                          maxAbsShap={maxAbsShap}
                        />
                      </li>
                    ))}
                  </ul>
                );
              })()
            )}
          </section>

          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {t("timeline")}
            </h3>
            {details.isLoading && !details.data ? (
              <div className="space-y-3">
                <Skeleton className="h-6 w-3/4" />
                <Skeleton className="h-6 w-1/2" />
              </div>
            ) : (
              <Timeline events={details.data?.timeline ?? []} />
            )}
          </section>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{t("emptyDetail")}</p>
      )}
    </Sheet>
  );
}

interface KeyValueProps {
  label: string;
  value: string;
  mono?: boolean;
}

function KeyValue({ label, value, mono = false }: KeyValueProps) {
  return (
    <div className="space-y-1">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <p className={cn("text-sm font-medium", mono && "font-mono")}>{value}</p>
    </div>
  );
}
