"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type { CalibracionBajaDTO, PrediccionBajaResult } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { prediccionKeys } from "@/lib/query-keys";

export type { PrediccionBajaResult };

/**
 * Intervalo de baja esperada (p10/p50/p90) del batch nocturno.
 *
 * Hook compartido desde que el simulador de puntuación (F2.2) usa el p90 como
 * baja del rival: el bloque de predicción y el simulador piden el mismo dato,
 * y la regla de `query-keys.ts` es que lo que se comparte es el hook, no sólo
 * la clave. El 404 (sin predicción ni adjudicación) no se reintenta.
 */
export function usePrediccionBaja(licitacionId: string) {
  return useQuery<PrediccionBajaResult>({
    queryKey: prediccionKeys.baja(licitacionId),
    queryFn: () =>
      fetchWithAuth<PrediccionBajaResult>(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/prediccion-baja`,
      ),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

/** Cobertura empírica del intervalo p10-p90 servido (`GET /predicciones/calibracion`). */
export function useCalibracionBaja() {
  return useQuery<CalibracionBajaDTO>({
    queryKey: prediccionKeys.calibracion,
    queryFn: () => fetchWithAuth("/api/v1/predicciones/calibracion"),
    staleTime: 10 * 60 * 1000,
    // El fallo se pinta en el panel: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });
}
