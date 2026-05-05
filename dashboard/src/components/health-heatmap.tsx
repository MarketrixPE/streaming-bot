"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import type { Account, AccountStatus } from "@/types/api";

interface HealthHeatmapProps {
  accounts: Account[];
  className?: string;
}

const STATUS_ORDER: AccountStatus[] = ["active", "warming", "quarantined", "banned"];

const STATUS_LABELS: Record<AccountStatus, string> = {
  active: "Active",
  warming: "Warming",
  quarantined: "Quarantined",
  banned: "Banned",
};

const toneForCount = (count: number, max: number): string => {
  if (max === 0 || count === 0) return "bg-muted/60 text-muted-foreground";
  const ratio = count / max;
  if (ratio < 0.15) return "bg-primary/10 text-foreground";
  if (ratio < 0.35) return "bg-primary/20 text-foreground";
  if (ratio < 0.6) return "bg-primary/35 text-primary-foreground";
  if (ratio < 0.8) return "bg-primary/60 text-primary-foreground";
  return "bg-primary text-primary-foreground";
};

export function HealthHeatmap({ accounts, className }: HealthHeatmapProps) {
  const { countries, counts, max } = React.useMemo(() => {
    const countrySet = new Set<string>();
    const tally = new Map<string, Map<AccountStatus, number>>();
    for (const account of accounts) {
      countrySet.add(account.country);
      const row = tally.get(account.country) ?? new Map<AccountStatus, number>();
      row.set(account.status, (row.get(account.status) ?? 0) + 1);
      tally.set(account.country, row);
    }
    const sortedCountries = Array.from(countrySet).sort();
    let maxValue = 0;
    for (const row of tally.values()) {
      for (const value of row.values()) {
        if (value > maxValue) maxValue = value;
      }
    }
    return { countries: sortedCountries, counts: tally, max: maxValue };
  }, [accounts]);

  if (countries.length === 0) {
    return (
      <div className={cn("rounded-xl border p-6 text-sm text-muted-foreground", className)}>
        Sin datos
      </div>
    );
  }

  return (
    <div className={cn("overflow-x-auto rounded-xl border bg-card", className)}>
      <table className="w-full min-w-[480px] text-sm">
        <thead>
          <tr className="border-b">
            <th className="p-3 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
              País
            </th>
            {STATUS_ORDER.map((status) => (
              <th
                key={status}
                className="p-3 text-center text-xs font-medium uppercase tracking-wide text-muted-foreground"
              >
                {STATUS_LABELS[status]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {countries.map((country) => {
            const row = counts.get(country);
            return (
              <tr key={country} className="border-b last:border-0">
                <td className="p-2 text-xs font-medium">{country}</td>
                {STATUS_ORDER.map((status) => {
                  const value = row?.get(status) ?? 0;
                  return (
                    <td key={status} className="p-2">
                      <div
                        className={cn(
                          "mx-auto flex h-9 w-16 items-center justify-center rounded-md text-xs font-semibold",
                          toneForCount(value, max),
                        )}
                        title={`${country} · ${STATUS_LABELS[status]}: ${value}`}
                      >
                        {value}
                      </div>
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
