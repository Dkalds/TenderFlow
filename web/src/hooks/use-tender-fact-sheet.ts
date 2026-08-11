"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiMutate, fetchWithAuth } from "@/lib/api-client";
import type {
  DeadlineFact,
  EvidenceRef,
  FactItem,
  MonetaryFact,
  TeamRequirement,
  TenderFactSheet,
  TenderFactSheetRecord,
  WeightedCriterion,
} from "@/lib/api-types";

/**
 * Tipos derivados del esquema OpenAPI, no escritos a mano.
 *
 * Los que había aquí divergían del contrato en tres formas a la vez: declaraban
 * como obligatorios campos que la API marca opcionales, aplanaban en un único
 * `FactItem` lo que el backend tipa por familia (`WeightedCriterion`,
 * `MonetaryFact`, `TeamRequirement`, `DeadlineFact`) y omitían `technologies`
 * por completo. Es exactamente el fallo que `api-types.ts` documenta: un tipo
 * a mano compila aunque la API nunca envíe ese campo.
 */
export type {
  DeadlineFact,
  EvidenceRef,
  FactItem,
  MonetaryFact,
  TeamRequirement,
  TenderFactSheet,
  TenderFactSheetRecord,
  WeightedCriterion,
};

export type FactSheetStatus = TenderFactSheetRecord["status"];

/**
 * Cualquier hecho de la ficha, sea de la familia que sea.
 *
 * Lo que comparten todas es `description`, `confidence` y `evidence`; el resto
 * de campos (`weight_pct`, `amount_eur`, `minimum_years`…) pertenece a una
 * familia concreta y hay que comprobarlo antes de leerlo.
 */
export type AnyFact =
  | FactItem
  | WeightedCriterion
  | MonetaryFact
  | TeamRequirement
  | DeadlineFact;

const key = (licitacionId: string) => ["tender-fact-sheet", licitacionId] as const;

export function useTenderFactSheet(licitacionId: string | null) {
  return useQuery({
    queryKey: key(licitacionId ?? ""),
    queryFn: () =>
      fetchWithAuth<TenderFactSheetRecord>(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId!)}/ficha-pliego`,
      ),
    enabled: Boolean(licitacionId),
    // A missing sheet is expected before the first explicit extraction, not an
    // application error.  The component renders that state as an actionable CTA.
    retry: (attempt, error) => !(error instanceof ApiError && error.status === 404) && attempt < 2,
  });
}

export function useExtractTenderFactSheet(licitacionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiMutate<TenderFactSheetRecord>(
        "POST",
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/ficha-pliego/extract`,
      ),
    onSuccess: (record) => queryClient.setQueryData(key(licitacionId), record),
  });
}
