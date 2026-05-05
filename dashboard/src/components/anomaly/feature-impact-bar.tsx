"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import type { FeatureContribution } from "@/types/anomaly";

interface FeatureImpactBarProps {
  feature: FeatureContribution;
  /** Mayor magnitud SHAP en el conjunto, usado para escalar el ancho. */
  maxAbsShap: number;
  className?: string;
}

const formatShap = (value: number): string => {
  const prefix = value >= 0 ? "+" : "";
  return `${prefix}${value.toFixed(3)}`;
};

const formatValue = (value: number): string =>
  Math.abs(value) >= 1
    ? value.toFixed(2)
    : value.toLocaleString("es-ES", { maximumFractionDigits: 3 });

/**
 * Barra horizontal divergente que representa el aporte SHAP de un feature.
 * - Magnitud relativa = |shapValue| / maxAbsShap (cap 100%).
 * - Negativo: barra crece hacia la izquierda y se pinta en rojo.
 * - Positivo: barra crece hacia la derecha y se pinta en verde.
 */
export function FeatureImpactBar({
  feature,
  maxAbsShap,
  className,
}: FeatureImpactBarProps) {
  const safeMax = maxAbsShap === 0 ? 1 : maxAbsShap;
  const ratio = Math.min(Math.abs(feature.shapValue) / safeMax, 1);
  const widthPct = `${(ratio * 100).toFixed(1)}%`;
  const positive = feature.shapValue >= 0;

  return (
    <div className={cn("space-y-1", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-xs font-medium">{feature.displayName}</span>
        <span className="font-mono text-[11px] text-muted-foreground">
          {formatShap(feature.shapValue)}
        </span>
      </div>
      <div className="relative grid h-2 w-full grid-cols-2 overflow-hidden rounded-full bg-muted/50">
        <div className="relative flex justify-end">
          {!positive ? (
            <div
              className="h-full rounded-l-full bg-destructive"
              style={{ width: widthPct }}
              aria-hidden
            />
          ) : null}
        </div>
        <div className="relative flex justify-start">
          {positive ? (
            <div
              className="h-full rounded-r-full bg-success"
              style={{ width: widthPct }}
              aria-hidden
            />
          ) : null}
        </div>
        <div
          className="pointer-events-none absolute left-1/2 top-0 h-full w-px bg-border"
          aria-hidden
        />
      </div>
      <div className="flex items-center justify-between text-[10px] text-muted-foreground">
        <span className="font-mono">{feature.name}</span>
        <span>{formatValue(feature.value)}</span>
      </div>
    </div>
  );
}

export const computeMaxAbsShap = (features: readonly FeatureContribution[]): number => {
  let max = 0;
  for (const f of features) {
    const abs = Math.abs(f.shapValue);
    if (abs > max) max = abs;
  }
  return max;
};
