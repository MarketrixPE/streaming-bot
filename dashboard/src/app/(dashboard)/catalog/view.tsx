"use client";

import * as React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useTranslations } from "next-intl";

import { Topbar } from "@/components/topbar";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useTracks, type CatalogFilters } from "@/lib/api-client";
import { formatNumber, formatPercent } from "@/lib/utils";
import type { Track, TrackStatus } from "@/types/api";

const DSP_OPTIONS = [
  { value: "spotify", label: "Spotify" },
  { value: "apple", label: "Apple Music" },
  { value: "amazon", label: "Amazon" },
  { value: "youtube", label: "YouTube" },
  { value: "deezer", label: "Deezer" },
  { value: "tidal", label: "Tidal" },
];

const DISTRO_OPTIONS = [
  { value: "distrokid", label: "DistroKid" },
  { value: "tunecore", label: "TuneCore" },
  { value: "cdbaby", label: "CD Baby" },
  { value: "amuse", label: "Amuse" },
  { value: "onerpm", label: "OneRPM" },
  { value: "ditto", label: "Ditto" },
];

const TIER_OPTIONS = ["S", "A", "B", "C", "D"].map((v) => ({ value: v, label: v }));
const STATUS_OPTIONS: Array<{ value: TrackStatus; label: string }> = [
  { value: "live", label: "Live" },
  { value: "pending", label: "Pending" },
  { value: "takedown", label: "Takedown" },
  { value: "paused", label: "Paused" },
];

const STATUS_VARIANT: Record<TrackStatus, BadgeProps["variant"]> = {
  live: "success",
  pending: "default",
  takedown: "destructive",
  paused: "warning",
};

export function CatalogView() {
  const t = useTranslations("catalog");
  const tCommon = useTranslations("common");
  const [filters, setFilters] = React.useState<CatalogFilters>({});
  const query = useTracks(filters);

  const update = <K extends keyof CatalogFilters>(key: K, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value.length > 0 ? value : undefined }));
  };

  const columns = React.useMemo<ColumnDef<Track>[]>(
    () => [
      {
        accessorKey: "coverUrl",
        header: t("columns.cover"),
        cell: ({ row }) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={row.original.coverUrl}
            alt={row.original.title}
            width={36}
            height={36}
            className="h-9 w-9 rounded-md object-cover"
          />
        ),
        enableSorting: false,
      },
      {
        accessorKey: "title",
        header: t("columns.title"),
        cell: ({ row }) => <span className="font-medium">{row.original.title}</span>,
      },
      {
        accessorKey: "artist",
        header: t("columns.artist"),
      },
      {
        accessorKey: "distributors",
        header: t("columns.distros"),
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            {row.original.distributors.map((d) => (
              <Badge key={d} variant="secondary" className="capitalize">
                {d}
              </Badge>
            ))}
          </div>
        ),
        enableSorting: false,
      },
      {
        accessorKey: "plays30d",
        header: t("columns.plays30d"),
        cell: ({ row }) => formatNumber(row.original.plays30d),
      },
      {
        accessorKey: "saveRate",
        header: t("columns.saveRate"),
        cell: ({ row }) => formatPercent(row.original.saveRate),
      },
      {
        accessorKey: "skipRate",
        header: t("columns.skipRate"),
        cell: ({ row }) => formatPercent(row.original.skipRate),
      },
      {
        accessorKey: "tier",
        header: t("columns.tier"),
        cell: ({ row }) => <Badge variant="outline">{row.original.tier}</Badge>,
      },
      {
        accessorKey: "status",
        header: t("columns.status"),
        cell: ({ row }) => (
          <Badge variant={STATUS_VARIANT[row.original.status]} className="capitalize">
            {row.original.status}
          </Badge>
        ),
      },
    ],
    [t],
  );

  return (
    <>
      <Topbar title={t("title")} subtitle={t("subtitle")} />
      <main className="flex flex-1 flex-col gap-6 p-6 lg:flex-row">
        <aside className="w-full shrink-0 lg:w-64">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">{t("filters.dsp")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1">
                <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t("filters.dsp")}
                </label>
                <Select
                  value={filters.dsp ?? ""}
                  onValueChange={(v) => update("dsp", v)}
                  options={DSP_OPTIONS}
                  includeAllOption={{ label: tCommon("all") }}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t("filters.tier")}
                </label>
                <Select
                  value={filters.tier ?? ""}
                  onValueChange={(v) => update("tier", v)}
                  options={TIER_OPTIONS}
                  includeAllOption={{ label: tCommon("all") }}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t("filters.distributor")}
                </label>
                <Select
                  value={filters.distributor ?? ""}
                  onValueChange={(v) => update("distributor", v)}
                  options={DISTRO_OPTIONS}
                  includeAllOption={{ label: tCommon("all") }}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t("filters.status")}
                </label>
                <Select
                  value={filters.status ?? ""}
                  onValueChange={(v) => update("status", v)}
                  options={STATUS_OPTIONS}
                  includeAllOption={{ label: tCommon("all") }}
                />
              </div>
              <Button
                variant="outline"
                onClick={() => setFilters({})}
                className="w-full"
              >
                {t("filters.reset")}
              </Button>
            </CardContent>
          </Card>
        </aside>

        <section className="flex-1">
          {query.isLoading ? (
            <Skeleton className="h-[480px] w-full" />
          ) : (
            <DataTable
              columns={columns}
              data={query.data ?? []}
              emptyMessage={t("empty")}
              initialPageSize={12}
            />
          )}
        </section>
      </main>
    </>
  );
}
