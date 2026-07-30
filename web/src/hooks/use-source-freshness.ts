"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";

export interface SourceFreshness {
  source: string;
  status: string;
  last_success_at: string | null;
  last_seen_updated: string | null;
  cursor_updated_at: string | null;
  lag_hours: number | null;
  detected_within_24h_pct: number | null;
  sample_size: number;
  fetched: number;
  parsed: number;
  discarded: number;
  errors: number;
  is_degraded: boolean;
  warning: string | null;
}

export interface SourceFreshnessResult {
  sources: SourceFreshness[];
  healthy_sources: number;
  total_sources: number;
  healthy_sources_pct: number;
  generated_at: string;
}

export function useSourceFreshness() {
  return useQuery({
    queryKey: ["analytics", "source-freshness"],
    queryFn: () => fetchWithAuth<SourceFreshnessResult>("/api/v1/analytics/source-freshness"),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });
}
