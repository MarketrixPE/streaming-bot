"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Pause,
  ShieldOff,
  Sparkles,
} from "lucide-react";

import { cn, formatRelative } from "@/lib/utils";
import type { AnomalyTimelineKind, TimelineEvent } from "@/types/anomaly";

interface TimelineProps {
  events: readonly TimelineEvent[];
  className?: string;
}

const KIND_ICON: Record<AnomalyTimelineKind, React.ComponentType<{ className?: string }>> = {
  detected: AlertTriangle,
  score_updated: Sparkles,
  acknowledged: CheckCircle2,
  snoozed: Pause,
  retired: ShieldOff,
  note: Clock,
};

const KIND_TONE: Record<AnomalyTimelineKind, string> = {
  detected: "bg-destructive/15 text-destructive",
  score_updated: "bg-primary/15 text-primary",
  acknowledged: "bg-success/15 text-success",
  snoozed: "bg-warning/15 text-warning",
  retired: "bg-muted text-muted-foreground",
  note: "bg-muted text-muted-foreground",
};

export function Timeline({ events, className }: TimelineProps) {
  const t = useTranslations("anomaly.timelineKind");
  const sorted = React.useMemo(
    () =>
      [...events].sort(
        (a, b) => new Date(a.at).getTime() - new Date(b.at).getTime(),
      ),
    [events],
  );

  if (sorted.length === 0) {
    return null;
  }

  return (
    <ol className={cn("relative space-y-4 border-l border-border pl-4", className)}>
      {sorted.map((event, idx) => {
        const Icon = KIND_ICON[event.kind];
        return (
          <li key={`${event.kind}-${event.at}-${idx}`} className="relative">
            <span
              className={cn(
                "absolute -left-[26px] flex h-5 w-5 items-center justify-center rounded-full",
                KIND_TONE[event.kind],
              )}
              aria-hidden
            >
              <Icon className="h-3 w-3" />
            </span>
            <div className="space-y-0.5">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="font-medium uppercase tracking-wide text-muted-foreground">
                  {t(event.kind)}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {formatRelative(event.at)}
                </span>
              </div>
              <p className="text-sm">{event.message}</p>
              {event.actor ? (
                <p className="text-[11px] text-muted-foreground">
                  <span className="font-mono">{event.actor}</span>
                </p>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
