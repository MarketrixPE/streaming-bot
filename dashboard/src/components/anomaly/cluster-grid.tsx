"use client";

import * as React from "react";

import { ClusterCard } from "@/components/anomaly/cluster-card";
import { cn } from "@/lib/utils";
import type { AnomalyCluster } from "@/types/anomaly";

interface ClusterGridProps {
  clusters: AnomalyCluster[];
  selectedKey: string | null;
  onSelect: (cluster: AnomalyCluster) => void;
  className?: string;
}

export function ClusterGrid({
  clusters,
  selectedKey,
  onSelect,
  className,
}: ClusterGridProps) {
  return (
    <div
      className={cn(
        "grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4",
        className,
      )}
    >
      {clusters.map((cluster) => (
        <ClusterCard
          key={cluster.key}
          cluster={cluster}
          selected={cluster.key === selectedKey}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
