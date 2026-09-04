"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type {
  HistoricalDistribution,
  PriceScenario,
  PriceScenariosResult,
} from "@/lib/api-types";
import { prediccionKeys } from "@/lib/query-keys";

export type { HistoricalDistribution, PriceScenario, PriceScenariosResult };

export function usePriceScenarios(licitacionId: string | null) {
  return useQuery({
    queryKey: prediccionKeys.escenarios(licitacionId),
    queryFn: () =>
      fetchWithAuth<PriceScenariosResult>(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId!)}/escenarios-precio`,
      ),
    enabled: Boolean(licitacionId),
    staleTime: 5 * 60_000,
  });
}
