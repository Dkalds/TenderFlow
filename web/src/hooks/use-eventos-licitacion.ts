"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth, type ApiGetResult } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { eventosKeys } from "@/lib/query-keys";

type TimelineResult = ApiGetResult<"/api/v1/licitaciones/{licitacion_id}/eventos">;

/** Cronología del contrato de una licitación (`GET /licitaciones/{id}/eventos`). */
export function useEventosLicitacion(licitacionId: string) {
  return useQuery<TimelineResult>({
    queryKey: eventosKeys.byLicitacion(licitacionId),
    queryFn: () => fetchWithAuth(`/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/eventos`),
    staleTime: 5 * 60 * 1000,
    // El fallo se pinta en el bloque (`PanelError`): sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });
}
