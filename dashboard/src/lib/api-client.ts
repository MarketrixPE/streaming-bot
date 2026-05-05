"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import {
  MOCK_ACCOUNTS,
  MOCK_ALERTS,
  MOCK_JOBS,
  MOCK_KPIS,
  MOCK_LIVE_EVENTS,
  MOCK_STREAMS_BY_DSP,
  MOCK_TRACKS,
  buildAnomalyDetail,
} from "@/lib/fixtures";
import type {
  Account,
  AnomalyAlert,
  AnomalyDetail,
  Job,
  LiveEvent,
  OverviewKpis,
  StreamsPerDspPoint,
  Track,
} from "@/types/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL?.trim() ?? "";
const USE_FIXTURES = API_BASE.length === 0;

class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
    credentials: "include",
  });
  if (!response.ok) {
    throw new ApiError(response.status, `API ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

const simulateLatency = <T>(value: T, ms = 120): Promise<T> =>
  new Promise((resolve) => {
    setTimeout(() => resolve(value), ms);
  });

export interface CatalogFilters {
  dsp?: string;
  tier?: string;
  distributor?: string;
  status?: string;
  search?: string;
}

export interface AccountsFilters {
  country?: string;
  tier?: string;
}

const filterTracks = (tracks: Track[], filters: CatalogFilters): Track[] => {
  const search = filters.search?.toLowerCase().trim() ?? "";
  return tracks.filter((t) => {
    if (filters.dsp && !t.dsps.includes(filters.dsp as Track["dsps"][number])) return false;
    if (filters.tier && t.tier !== filters.tier) return false;
    if (
      filters.distributor &&
      !t.distributors.includes(filters.distributor as Track["distributors"][number])
    ) {
      return false;
    }
    if (filters.status && t.status !== filters.status) return false;
    if (search) {
      return (
        t.title.toLowerCase().includes(search) || t.artist.toLowerCase().includes(search)
      );
    }
    return true;
  });
};

const filterAccounts = (accounts: Account[], filters: AccountsFilters): Account[] =>
  accounts.filter((a) => {
    if (filters.country && a.country !== filters.country) return false;
    if (filters.tier && a.tier !== filters.tier) return false;
    return true;
  });

export const api = {
  async getOverviewKpis(): Promise<OverviewKpis> {
    if (USE_FIXTURES) return simulateLatency(MOCK_KPIS);
    return apiFetch<OverviewKpis>("/api/overview/kpis");
  },
  async getLiveEvents(): Promise<LiveEvent[]> {
    if (USE_FIXTURES) return simulateLatency(MOCK_LIVE_EVENTS);
    return apiFetch<LiveEvent[]>("/api/overview/live-events");
  },
  async getStreamsByDsp(): Promise<StreamsPerDspPoint[]> {
    if (USE_FIXTURES) return simulateLatency(MOCK_STREAMS_BY_DSP);
    return apiFetch<StreamsPerDspPoint[]>("/api/overview/streams-by-dsp");
  },
  async listTracks(filters: CatalogFilters): Promise<Track[]> {
    if (USE_FIXTURES) return simulateLatency(filterTracks(MOCK_TRACKS, filters));
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(filters)) {
      if (v) params.set(k, v);
    }
    return apiFetch<Track[]>(`/api/catalog?${params.toString()}`);
  },
  async listAccounts(filters: AccountsFilters): Promise<Account[]> {
    if (USE_FIXTURES) return simulateLatency(filterAccounts(MOCK_ACCOUNTS, filters));
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(filters)) {
      if (v) params.set(k, v);
    }
    return apiFetch<Account[]>(`/api/accounts?${params.toString()}`);
  },
  async listJobs(): Promise<Job[]> {
    if (USE_FIXTURES) return simulateLatency(MOCK_JOBS);
    return apiFetch<Job[]>("/api/jobs");
  },
  async getAnomalies(): Promise<AnomalyAlert[]> {
    if (USE_FIXTURES) return simulateLatency([...MOCK_ALERTS]);
    return apiFetch<AnomalyAlert[]>("/api/anomaly");
  },
  async getAnomalyDetails(accountId: string): Promise<AnomalyDetail> {
    if (USE_FIXTURES) {
      const alert = MOCK_ALERTS.find((a) => a.accountId === accountId);
      if (!alert) throw new ApiError(404, "anomaly_not_found");
      return simulateLatency(buildAnomalyDetail(alert), 80);
    }
    const params = new URLSearchParams({ account_id: accountId });
    return apiFetch<AnomalyDetail>(`/api/anomaly/details?${params.toString()}`);
  },
  async acknowledgeAnomaly(id: string): Promise<AnomalyAlert> {
    if (USE_FIXTURES) {
      const found = MOCK_ALERTS.find((a) => a.id === id);
      if (!found) throw new ApiError(404, "anomaly_not_found");
      found.status = "acknowledged";
      found.ackAt = new Date().toISOString();
      return simulateLatency({ ...found });
    }
    return apiFetch<AnomalyAlert>(`/api/anomaly/${id}/ack`, { method: "POST" });
  },
  async retireAccount(accountId: string): Promise<AnomalyAlert[]> {
    if (USE_FIXTURES) {
      const now = new Date().toISOString();
      const updated: AnomalyAlert[] = [];
      for (const alert of MOCK_ALERTS) {
        if (alert.accountId !== accountId) continue;
        alert.status = "retired";
        alert.retireAt = now;
        updated.push({ ...alert });
      }
      if (updated.length === 0) throw new ApiError(404, "account_not_found");
      return simulateLatency(updated);
    }
    return apiFetch<AnomalyAlert[]>(`/api/accounts/${accountId}/retire`, { method: "POST" });
  },
  async snoozeAnomaly(input: { id: string; hours: number }): Promise<AnomalyAlert> {
    if (USE_FIXTURES) {
      const found = MOCK_ALERTS.find((a) => a.id === input.id);
      if (!found) throw new ApiError(404, "anomaly_not_found");
      const until = new Date(Date.now() + input.hours * 60 * 60 * 1000).toISOString();
      found.status = "snoozed";
      found.snoozeUntil = until;
      return simulateLatency({ ...found });
    }
    return apiFetch<AnomalyAlert>(`/api/anomaly/${input.id}/snooze`, {
      method: "POST",
      body: JSON.stringify({ hours: input.hours }),
    });
  },
} as const;

export const queryKeys = {
  overviewKpis: ["overview", "kpis"] as const,
  liveEvents: ["overview", "live-events"] as const,
  streamsByDsp: ["overview", "streams-by-dsp"] as const,
  catalog: (filters: CatalogFilters) => ["catalog", filters] as const,
  accounts: (filters: AccountsFilters) => ["accounts", filters] as const,
  jobs: ["jobs"] as const,
  anomalies: ["anomalies"] as const,
  anomalyDetail: (accountId: string) => ["anomalies", "detail", accountId] as const,
};

export function useOverviewKpis(): UseQueryResult<OverviewKpis, Error> {
  return useQuery({
    queryKey: queryKeys.overviewKpis,
    queryFn: () => api.getOverviewKpis(),
    staleTime: 30_000,
  });
}

export function useLiveEvents(): UseQueryResult<LiveEvent[], Error> {
  return useQuery({
    queryKey: queryKeys.liveEvents,
    queryFn: () => api.getLiveEvents(),
    refetchInterval: 15_000,
  });
}

export function useStreamsByDsp(): UseQueryResult<StreamsPerDspPoint[], Error> {
  return useQuery({
    queryKey: queryKeys.streamsByDsp,
    queryFn: () => api.getStreamsByDsp(),
    staleTime: 60_000,
  });
}

export function useTracks(filters: CatalogFilters): UseQueryResult<Track[], Error> {
  return useQuery({
    queryKey: queryKeys.catalog(filters),
    queryFn: () => api.listTracks(filters),
    staleTime: 10_000,
  });
}

export function useAccounts(filters: AccountsFilters): UseQueryResult<Account[], Error> {
  return useQuery({
    queryKey: queryKeys.accounts(filters),
    queryFn: () => api.listAccounts(filters),
    staleTime: 10_000,
  });
}

export function useJobs(): UseQueryResult<Job[], Error> {
  return useQuery({
    queryKey: queryKeys.jobs,
    queryFn: () => api.listJobs(),
    refetchInterval: 5_000,
  });
}

export { ApiError, USE_FIXTURES };
