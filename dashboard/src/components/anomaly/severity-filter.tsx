"use client";

import * as React from "react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import { SEVERITY_ORDER, type AnomalySeverity } from "@/types/anomaly";

interface SeverityFilterProps {
  value: ReadonlySet<AnomalySeverity>;
  onChange: (next: Set<AnomalySeverity>) => void;
  className?: string;
}

const SEVERITY_BADGE: Record<AnomalySeverity, string> = {
  LOW: "bg-muted text-foreground",
  MEDIUM: "bg-warning/15 text-warning",
  HIGH: "bg-orange-500/15 text-orange-500",
  CRITICAL: "bg-destructive/15 text-destructive",
};

const SEVERITY_ACTIVE: Record<AnomalySeverity, string> = {
  LOW: "border-foreground bg-foreground/10",
  MEDIUM: "border-warning bg-warning/15",
  HIGH: "border-orange-500 bg-orange-500/15",
  CRITICAL: "border-destructive bg-destructive/15",
};

export function SeverityFilter({ value, onChange, className }: SeverityFilterProps) {
  const t = useTranslations("anomaly.severity");

  const toggle = (severity: AnomalySeverity) => {
    const next = new Set(value);
    if (next.has(severity)) next.delete(severity);
    else next.add(severity);
    onChange(next);
  };

  return (
    <div
      role="group"
      aria-label="severity filter"
      className={cn("flex flex-wrap items-center gap-2", className)}
    >
      {SEVERITY_ORDER.map((severity) => {
        const active = value.has(severity);
        return (
          <button
            key={severity}
            type="button"
            onClick={() => toggle(severity)}
            aria-pressed={active}
            className={cn(
              "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium transition",
              "hover:bg-accent",
              active ? SEVERITY_ACTIVE[severity] : "border-border bg-card",
            )}
          >
            <span
              className={cn(
                "inline-flex h-1.5 w-1.5 rounded-full",
                SEVERITY_BADGE[severity],
              )}
              aria-hidden
            />
            <span className="uppercase tracking-wide">{t(severity)}</span>
          </button>
        );
      })}
    </div>
  );
}
