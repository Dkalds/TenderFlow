"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiMutate, fetchWithAuth } from "@/lib/api-client";

export type FactSheetStatus = "pending" | "extracted" | "needs_review" | "failed";

export interface FactEvidence {
  documento_id: number;
  page_number: number;
  quote: string;
  start_offset: number | null;
  end_offset: number | null;
}

export interface FactItem {
  description: string;
  confidence: number;
  evidence: FactEvidence[];
  name?: string;
  weight_pct?: number | null;
  criterion_type?: "price" | "quality" | "automatic" | "judgement" | "other";
  amount_eur?: number | null;
  role?: string | null;
  minimum_years?: number | null;
  quantity?: number | null;
  date_value?: string | null;
}

export interface TenderFactSheet {
  award_criteria: FactItem[];
  technical_solvency: FactItem[];
  economic_solvency: FactItem[];
  guarantees: FactItem[];
  penalties: FactItem[];
  subcontracting: FactItem[];
  team_requirements: FactItem[];
  extensions: FactItem[];
  critical_deadlines: FactItem[];
}

export interface TenderFactSheetRecord {
  licitacion_id: string;
  status: FactSheetStatus;
  extraction_version: string;
  model: string | null;
  facts: TenderFactSheet | null;
  field_count: number;
  evidence_count: number;
  error_detail: string | null;
  extracted_at: string | null;
  updated_at: string;
}

const key = (licitacionId: string) => ["tender-fact-sheet", licitacionId] as const;

export function useTenderFactSheet(licitacionId: string | null) {
  return useQuery({
    queryKey: key(licitacionId ?? ""),
    queryFn: () => fetchWithAuth<TenderFactSheetRecord>(`/api/v1/licitaciones/${encodeURIComponent(licitacionId!)}/ficha-pliego`),
    enabled: Boolean(licitacionId),
    // A missing sheet is expected before the first explicit extraction, not an
    // application error.  The component renders that state as an actionable CTA.
    retry: (attempt, error) => !(error instanceof ApiError && error.status === 404) && attempt < 2,
  });
}

export function useExtractTenderFactSheet(licitacionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiMutate<TenderFactSheetRecord>("POST", `/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/ficha-pliego/extract`),
    onSuccess: (record) => queryClient.setQueryData(key(licitacionId), record),
  });
}
