"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api-client";
import type { SourceFreshness, SourceFreshnessResult } from "@/lib/api-types";
import { analyticsKeys } from "@/lib/query-keys";

export type { SourceFreshness, SourceFreshnessResult };

export function useSourceFreshness() {
  return useQuery({
    queryKey: analyticsKeys.sourceFreshness,
    queryFn: () => apiGet("/api/v1/analytics/source-freshness"),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });
}
