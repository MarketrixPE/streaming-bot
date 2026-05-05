import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export interface KpiCardProps {
  title: string;
  value: string;
  delta?: number;
  loading?: boolean;
  hint?: string;
  invertDelta?: boolean;
}

export function KpiCard({ title, value, delta, loading, hint, invertDelta }: KpiCardProps) {
  const direction = delta === undefined ? null : delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  const positive = invertDelta ? direction === "down" : direction === "up";
  const negative = invertDelta ? direction === "up" : direction === "down";

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-end justify-between gap-2">
          <div className="flex flex-col gap-1">
            {loading ? (
              <Skeleton className="h-7 w-24" />
            ) : (
              <span className="text-2xl font-semibold tracking-tight">{value}</span>
            )}
            {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
          </div>
          {direction ? (
            <span
              className={cn(
                "flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
                positive && "bg-success/15 text-success",
                negative && "bg-destructive/15 text-destructive",
                direction === "flat" && "bg-muted text-muted-foreground",
              )}
            >
              {direction === "up" ? (
                <ArrowUpRight className="h-3 w-3" />
              ) : direction === "down" ? (
                <ArrowDownRight className="h-3 w-3" />
              ) : (
                <Minus className="h-3 w-3" />
              )}
              {delta !== undefined
                ? `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(1)}%`
                : null}
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
