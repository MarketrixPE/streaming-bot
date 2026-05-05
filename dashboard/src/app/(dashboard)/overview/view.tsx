"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";

import { Topbar } from "@/components/topbar";
import { KpiCard } from "@/components/kpi-card";
import { AreaChart } from "@/components/charts/area-chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useLiveEvents,
  useOverviewKpis,
  useStreamsByDsp,
} from "@/lib/api-client";
import { formatCurrency, formatNumber } from "@/lib/utils";
import type { WorldMapMarker } from "@/components/charts/world-map";

const WorldMap = dynamic(() => import("@/components/charts/world-map"), {
  ssr: false,
  loading: () => <Skeleton className="h-[360px] w-full" />,
});

export function OverviewView() {
  const t = useTranslations("overview");
  const kpis = useOverviewKpis();
  const events = useLiveEvents();
  const streamsByDsp = useStreamsByDsp();

  const markers: WorldMapMarker[] = React.useMemo(
    () =>
      (events.data ?? []).map((e) => ({
        id: e.id,
        lng: e.lng,
        lat: e.lat,
        tone: "primary",
        label: `${e.city} · ${e.dsp}`,
      })),
    [events.data],
  );

  const chartData = React.useMemo(
    () =>
      (streamsByDsp.data ?? []).map((point) => ({
        hour: new Date(point.hour).toLocaleTimeString("es-ES", {
          hour: "2-digit",
          minute: "2-digit",
        }),
        spotify: point.spotify,
        apple: point.apple,
        amazon: point.amazon,
        youtube: point.youtube,
        deezer: point.deezer,
        tidal: point.tidal,
      })),
    [streamsByDsp.data],
  );

  return (
    <>
      <Topbar title={t("title")} subtitle={t("subtitle")} />
      <main className="flex flex-1 flex-col gap-6 p-6">
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <KpiCard
            title={t("kpi.streams24h")}
            value={kpis.data ? formatNumber(kpis.data.streams24h) : "-"}
            delta={kpis.data?.streams24hDelta}
            loading={kpis.isLoading}
          />
          <KpiCard
            title={t("kpi.activeAccounts")}
            value={kpis.data ? formatNumber(kpis.data.activeAccounts) : "-"}
            delta={kpis.data?.activeAccountsDelta}
            loading={kpis.isLoading}
          />
          <KpiCard
            title={t("kpi.costPerStream")}
            value={kpis.data ? formatCurrency(kpis.data.costPerStream) : "-"}
            delta={kpis.data?.costPerStreamDelta}
            loading={kpis.isLoading}
            invertDelta
          />
          <KpiCard
            title={t("kpi.revenue7d")}
            value={kpis.data ? formatCurrency(kpis.data.revenue7d) : "-"}
            delta={kpis.data?.revenue7dDelta}
            loading={kpis.isLoading}
          />
        </section>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div>
              <CardTitle>{t("map.title")}</CardTitle>
              <p className="text-sm text-muted-foreground">{t("map.subtitle")}</p>
            </div>
          </CardHeader>
          <CardContent>
            <div className="h-[360px] w-full">
              <WorldMap markers={markers} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("byDsp.title")}</CardTitle>
            <p className="text-sm text-muted-foreground">{t("byDsp.subtitle")}</p>
          </CardHeader>
          <CardContent>
            {streamsByDsp.isLoading ? (
              <Skeleton className="h-72 w-full" />
            ) : (
              <AreaChart
                data={chartData}
                index="hour"
                categories={["spotify", "apple", "amazon", "youtube", "deezer", "tidal"]}
                valueFormatter={(v) => formatNumber(v)}
                className="h-72"
              />
            )}
          </CardContent>
        </Card>
      </main>
    </>
  );
}
