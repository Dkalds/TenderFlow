"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type { PrediccionBajaResult } from "@/lib/api-types";
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
