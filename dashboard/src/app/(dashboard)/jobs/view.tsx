"use client";

import * as React from "react";
import { useTranslations } from "next-intl";

import { Topbar } from "@/components/topbar";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useJobs } from "@/lib/api-client";
import { formatRelative } from "@/lib/utils";
import type { Job, JobStatus } from "@/types/api";

const STATUS_VARIANT: Record<JobStatus, BadgeProps["variant"]> = {
  running: "default",
  pending: "secondary",
  completed: "success",
  failed: "destructive",
};

const formatEta = (seconds: number | null): string => {
  if (seconds === null || seconds <= 0) return "-";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return remaining === 0 ? `${minutes}m` : `${minutes}m ${remaining}s`;
};

export function JobsView() {
  const t = useTranslations("jobs");
  const query = useJobs();

  const summary = React.useMemo(() => {
    const counts: Record<JobStatus, number> = {
      running: 0,
      pending: 0,
      completed: 0,
      failed: 0,
    };
    for (const job of query.data ?? []) {
      counts[job.status] += 1;
    }
    return counts;
  }, [query.data]);

  const inProgress = React.useMemo<Job[]>(
    () => (query.data ?? []).filter((j) => j.status !== "completed"),
    [query.data],
  );

  return (
    <>
      <Topbar title={t("title")} subtitle={t("subtitle")} />
      <main className="flex flex-1 flex-col gap-6 p-6">
        <Card>
          <CardHeader>
            <CardTitle>{t("queue")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {(Object.keys(summary) as JobStatus[]).map((status) => (
                <div
                  key={status}
                  className="flex items-center justify-between rounded-lg border bg-muted/40 p-4"
                >
                  <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {t(`status.${status}`)}
                  </span>
                  <span className="text-xl font-semibold">{summary[status]}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("inProgress")}</CardTitle>
          </CardHeader>
          <CardContent>
            {query.isLoading ? (
              <Skeleton className="h-80 w-full" />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("columns.id")}</TableHead>
                    <TableHead>{t("columns.workflow")}</TableHead>
                    <TableHead>{t("columns.worker")}</TableHead>
                    <TableHead>{t("columns.progress")}</TableHead>
                    <TableHead>{t("columns.eta")}</TableHead>
                    <TableHead>{t("columns.startedAt")}</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {inProgress.map((job) => (
                    <TableRow key={job.id}>
                      <TableCell className="font-mono text-xs">{job.id}</TableCell>
                      <TableCell className="font-medium">{job.workflow}</TableCell>
                      <TableCell className="text-muted-foreground">{job.worker}</TableCell>
                      <TableCell className="w-48">
                        <div className="flex items-center gap-2">
                          <Progress value={job.progress} />
                          <span className="w-10 text-right text-xs font-medium">
                            {Math.round(job.progress * 100)}%
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="text-xs">{formatEta(job.etaSeconds)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatRelative(job.startedAt)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={STATUS_VARIANT[job.status]} className="capitalize">
                          {t(`status.${job.status}`)}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </main>
    </>
  );
}
