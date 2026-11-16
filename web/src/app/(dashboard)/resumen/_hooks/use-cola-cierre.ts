"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchWithAuth } from "@/lib/api-client";
import type { LicitacionesCursorPage } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { licitacionesKeys } from "@/lib/query-keys";

/**
 * Las filas de la cola de cierre (`cola-cierre.tsx`): el cursor de
 * licitaciones con el ámbito y la ventana de 48 h que arma la tarjeta.
 * `enabled` es falso cuando el contador ya dice que no hay cola.
 */
export function useColaCierre(params: Record<string, string>, enabled: boolean) {
  return useQuery<LicitacionesCursorPage>({
    queryKey: licitacionesKeys.colaCierre(params),
    queryFn: ({ signal }) =>
      fetchWithAuth<LicitacionesCursorPage>(`/api/v1/licitaciones/cursor?${new URLSearchParams(params)}`, {
        signal,
      }),
    staleTime: 2 * 60 * 1000,
    enabled,
    // El fallo del desglose se dice dentro de la tarjeta: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });
}
