"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";

export interface HistoricalDistribution {
  n: number;
  p10_discount: number;
  p25_discount: number;
  p50_discount: number;
  p75_discount: number;
  p90_discount: number;
  observed_interval: [number, number];
}

export interface PriceScenario {
  name: "defensivo" | "central" | "competitivo";
  discount: number;
  price_eur: number;
  basis: string;
}

export interface PriceScenariosResult {
  licitacion_id: string;
  tender_amount_eur: number;
  expected_competition: number | null;
  cohort: string[];
  sample_quality: "robusta" | "indicativa" | "insuficiente";
  distribution: HistoricalDistribution | null;
  scenarios: PriceScenario[];
  win_probability_gate: {
    available: boolean;
    blockers: string[];
  };
  methodology: string;
  disclaimer: string;
}

export function usePriceScenarios(licitacionId: string | null) {
  return useQuery({
    queryKey: ["price-scenarios", licitacionId],
    queryFn: () =>
      fetchWithAuth<PriceScenariosResult>(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId!)}/escenarios-precio`,
      ),
    enabled: Boolean(licitacionId),
    staleTime: 5 * 60_000,
  });
}
