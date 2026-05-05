"use client";

import * as React from "react";
import { useTranslations } from "next-intl";

import { Topbar } from "@/components/topbar";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { HealthHeatmap } from "@/components/health-heatmap";
import { useAccounts, type AccountsFilters } from "@/lib/api-client";
import { formatRelative } from "@/lib/utils";
import type { AccountStatus } from "@/types/api";

const COUNTRY_OPTIONS = ["US", "MX", "BR", "DE", "ES", "FR", "GB", "JP", "AR", "CO"].map(
  (c) => ({ value: c, label: c }),
);

const TIER_OPTIONS = ["S", "A", "B", "C", "D"].map((v) => ({ value: v, label: v }));

const STATUS_VARIANT: Record<AccountStatus, BadgeProps["variant"]> = {
  active: "success",
  warming: "default",
  quarantined: "warning",
  banned: "destructive",
};

export function AccountsView() {
  const t = useTranslations("accounts");
  const tCommon = useTranslations("common");
  const [filters, setFilters] = React.useState<AccountsFilters>({});
  const query = useAccounts(filters);

  const update = <K extends keyof AccountsFilters>(key: K, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value.length > 0 ? value : undefined }));
  };

  return (
    <>
      <Topbar title={t("title")} subtitle={t("subtitle")} />
      <main className="flex flex-1 flex-col gap-6 p-6">
        <Card>
          <CardHeader className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <CardTitle>{t("heatmap")}</CardTitle>
              <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
            </div>
            <div className="grid grid-cols-2 gap-2 md:w-auto md:gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                  {t("filters.country")}
                </label>
                <Select
                  value={filters.country ?? ""}
                  onValueChange={(v) => update("country", v)}
                  options={COUNTRY_OPTIONS}
                  includeAllOption={{ label: tCommon("all") }}
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                  {t("filters.tier")}
                </label>
                <Select
                  value={filters.tier ?? ""}
                  onValueChange={(v) => update("tier", v)}
                  options={TIER_OPTIONS}
                  includeAllOption={{ label: tCommon("all") }}
                />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {query.isLoading ? (
              <Skeleton className="h-56 w-full" />
            ) : (
              <HealthHeatmap accounts={query.data ?? []} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("list")}</CardTitle>
          </CardHeader>
          <CardContent>
            {query.isLoading ? (
              <Skeleton className="h-80 w-full" />
            ) : (
              <ul className="divide-y">
                {(query.data ?? []).slice(0, 20).map((account) => (
                  <li
                    key={account.id}
                    className="flex flex-col gap-3 py-3 md:flex-row md:items-center md:justify-between"
                  >
                    <div className="flex min-w-0 flex-col">
                      <span className="truncate text-sm font-medium">{account.label}</span>
                      <span className="text-xs text-muted-foreground">
                        {account.dsp} · {account.country} · tier {account.tier}
                      </span>
                    </div>
                    <div className="flex flex-1 items-center gap-4 md:max-w-md">
                      <div className="flex-1">
                        <div className="mb-1 flex items-center justify-between text-xs">
                          <span className="text-muted-foreground">{t("healthScore")}</span>
                          <span className="font-medium">{account.healthScore}</span>
                        </div>
                        <Progress value={account.healthScore} max={100} />
                      </div>
                      <Badge variant={STATUS_VARIANT[account.status]} className="capitalize">
                        {t(`status.${account.status}`)}
                      </Badge>
                    </div>
                    <span className="text-xs text-muted-foreground md:ml-4">
                      {t("lastAction")}: {formatRelative(account.lastActionAt)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </main>
    </>
  );
}
