"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiMutate, fetchWithAuth } from "@/lib/api-client";
import type {
  CertificationRequirement,
  DeadlineFact,
  DocumentosResult,
  EvidenceRef,
  FactItem,
  FactSheetExtractionState,
  LotFact,
  MonetaryFact,
  ServiceLevelFact,
  TeamRequirement,
  TenderFactSheet,
  TenderFactSheetRecord,
  WeightedCriterion,
} from "@/lib/api-types";
import { documentosKeys } from "@/lib/query-keys";

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
  CertificationRequirement,
  DeadlineFact,
  EvidenceRef,
  FactItem,
  LotFact,
  MonetaryFact,
  ServiceLevelFact,
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
  | DeadlineFact
  | LotFact
  | CertificationRequirement
  | ServiceLevelFact;

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

/**
 * Metadatos de los documentos de la licitación, para resolver
 * `documento_id → filename/uri` en las citas de la ficha. Comparte queryKey con
 * `DocumentosBlock`, así que abrir la pestaña Pliegos no repite la petición.
 */
export function useFactSheetDocumentos(licitacionId: string) {
  return useQuery({
    queryKey: documentosKeys.byLicitacion(licitacionId),
    queryFn: () =>
      fetchWithAuth<DocumentosResult>(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/documentos`,
      ),
    enabled: Boolean(licitacionId),
    staleTime: 5 * 60 * 1000,
  });
}

const estadoKey = (licitacionId: string) => ["tender-fact-sheet-estado", licitacionId] as const;

/**
 * Extracción en background (`extract-async` + polling de `/estado`).
 *
 * El camino síncrono (`useExtractTenderFactSheet`) mantiene la request abierta
 * mientras se descargan hasta 8 PDFs y responde el LLM — minutos de spinner y
 * un timeout de proxy esperando a pasar. Aquí el POST devuelve 202 al momento;
 * el estado se sondea cada pocos segundos y, al terminar, se refresca la ficha.
 */
export function useTenderFactSheetExtraction(licitacionId: string) {
  const queryClient = useQueryClient();

  const estado = useQuery({
    queryKey: estadoKey(licitacionId),
    queryFn: () =>
      fetchWithAuth<FactSheetExtractionState>(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/ficha-pliego/estado`,
      ),
    enabled: Boolean(licitacionId),
    // Sondeo solo mientras hay trabajo en curso; parado, es una lectura única.
    refetchInterval: (query) => (query.state.data?.running ? 2500 : false),
  });

  const running = estado.data?.running === true;

  // Transición running → parado: la ficha (nueva o failed) ya está persistida.
  const wasRunning = React.useRef(false);
  React.useEffect(() => {
    if (wasRunning.current && !running) {
      void queryClient.invalidateQueries({ queryKey: key(licitacionId) });
    }
    wasRunning.current = running;
  }, [running, licitacionId, queryClient]);

  const start = useMutation({
    mutationFn: () =>
      apiMutate<FactSheetExtractionState>(
        "POST",
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/ficha-pliego/extract-async`,
      ),
    onSuccess: (state) => queryClient.setQueryData(estadoKey(licitacionId), state),
  });

  return {
    start: () => start.mutateAsync(),
    isStarting: start.isPending,
    running,
  };
}
