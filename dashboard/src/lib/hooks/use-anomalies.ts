"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { api, queryKeys } from "@/lib/api-client";
import type { AnomalyAlert, AnomalyDetail, AnomalyStatus } from "@/types/anomaly";

const ANOMALIES_POLL_MS = 10_000;
const DETAILS_POLL_MS = 30_000;

export function useAnomalies(): UseQueryResult<AnomalyAlert[], Error> {
  return useQuery({
    queryKey: queryKeys.anomalies,
    queryFn: () => api.getAnomalies(),
    refetchInterval: ANOMALIES_POLL_MS,
    staleTime: 5_000,
  });
}

export interface UseAnomalyDetailsOptions {
  /** Cuando false, deshabilita la query y el polling. */
  enabled?: boolean;
}

export function useAnomalyDetails(
  accountId: string | null,
  options: UseAnomalyDetailsOptions = {},
): UseQueryResult<AnomalyDetail, Error> {
  const enabled = (options.enabled ?? true) && accountId !== null;
  return useQuery({
    queryKey: queryKeys.anomalyDetail(accountId ?? "__none__"),
    queryFn: () => {
      if (!accountId) {
        throw new Error("accountId requerido");
      }
      return api.getAnomalyDetails(accountId);
    },
    enabled,
    refetchInterval: enabled ? DETAILS_POLL_MS : false,
    staleTime: 10_000,
  });
}

interface ListMutationContext {
  previous: AnomalyAlert[] | undefined;
}

const updateInList = (
  list: AnomalyAlert[],
  predicate: (alert: AnomalyAlert) => boolean,
  patch: (alert: AnomalyAlert) => AnomalyAlert,
): AnomalyAlert[] => list.map((a) => (predicate(a) ? patch(a) : a));

export function useAcknowledgeAnomaly(): UseMutationResult<
  AnomalyAlert,
  Error,
  string,
  ListMutationContext
> {
  const qc = useQueryClient();
  return useMutation<AnomalyAlert, Error, string, ListMutationContext>({
    mutationFn: (id: string) => api.acknowledgeAnomaly(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: queryKeys.anomalies });
      const previous = qc.getQueryData<AnomalyAlert[]>(queryKeys.anomalies);
      if (previous) {
        const ackAt = new Date().toISOString();
        const status: AnomalyStatus = "acknowledged";
        qc.setQueryData<AnomalyAlert[]>(
          queryKeys.anomalies,
          updateInList(
            previous,
            (a) => a.id === id,
            (a) => ({ ...a, status, ackAt }),
          ),
        );
      }
      return { previous };
    },
    onError: (_err, _id, ctx) => {
      if (ctx?.previous) qc.setQueryData(queryKeys.anomalies, ctx.previous);
    },
    onSettled: (data) => {
      void qc.invalidateQueries({ queryKey: queryKeys.anomalies });
      if (data) {
        void qc.invalidateQueries({
          queryKey: queryKeys.anomalyDetail(data.accountId),
        });
      }
    },
  });
}

export function useRetireAccount(): UseMutationResult<
  AnomalyAlert[],
  Error,
  string,
  ListMutationContext
> {
  const qc = useQueryClient();
  return useMutation<AnomalyAlert[], Error, string, ListMutationContext>({
    mutationFn: (accountId: string) => api.retireAccount(accountId),
    onMutate: async (accountId) => {
      await qc.cancelQueries({ queryKey: queryKeys.anomalies });
      const previous = qc.getQueryData<AnomalyAlert[]>(queryKeys.anomalies);
      if (previous) {
        const retireAt = new Date().toISOString();
        const status: AnomalyStatus = "retired";
        qc.setQueryData<AnomalyAlert[]>(
          queryKeys.anomalies,
          updateInList(
            previous,
            (a) => a.accountId === accountId,
            (a) => ({ ...a, status, retireAt }),
          ),
        );
      }
      return { previous };
    },
    onError: (_err, _accountId, ctx) => {
      if (ctx?.previous) qc.setQueryData(queryKeys.anomalies, ctx.previous);
    },
    onSettled: (_data, _err, accountId) => {
      void qc.invalidateQueries({ queryKey: queryKeys.anomalies });
      void qc.invalidateQueries({ queryKey: queryKeys.anomalyDetail(accountId) });
    },
  });
}

export interface SnoozeAnomalyInput {
  id: string;
  hours: number;
}

export function useSnoozeAnomaly(): UseMutationResult<
  AnomalyAlert,
  Error,
  SnoozeAnomalyInput,
  ListMutationContext
> {
  const qc = useQueryClient();
  return useMutation<AnomalyAlert, Error, SnoozeAnomalyInput, ListMutationContext>({
    mutationFn: ({ id, hours }) => api.snoozeAnomaly({ id, hours }),
    onMutate: async ({ id, hours }) => {
      await qc.cancelQueries({ queryKey: queryKeys.anomalies });
      const previous = qc.getQueryData<AnomalyAlert[]>(queryKeys.anomalies);
      if (previous) {
        const snoozeUntil = new Date(Date.now() + hours * 60 * 60 * 1000).toISOString();
        const status: AnomalyStatus = "snoozed";
        qc.setQueryData<AnomalyAlert[]>(
          queryKeys.anomalies,
          updateInList(
            previous,
            (a) => a.id === id,
            (a) => ({ ...a, status, snoozeUntil }),
          ),
        );
      }
      return { previous };
    },
    onError: (_err, _input, ctx) => {
      if (ctx?.previous) qc.setQueryData(queryKeys.anomalies, ctx.previous);
    },
    onSettled: (data) => {
      void qc.invalidateQueries({ queryKey: queryKeys.anomalies });
      if (data) {
        void qc.invalidateQueries({
          queryKey: queryKeys.anomalyDetail(data.accountId),
        });
      }
    },
  });
}
