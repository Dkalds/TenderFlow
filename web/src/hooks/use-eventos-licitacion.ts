"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { eventosKeys } from "@/lib/query-keys";

export interface EventoContrato {
  fecha: string | null;
  tipo: string;
  campo: string | null;
  valor_antes: string | null;
  valor_despues: string | null;
  importe_delta: number | null;
  detalle: string | null;
}

/** Cronología del contrato de una licitación (`GET /licitaciones/{id}/eventos`). */
export function useEventosLicitacion(licitacionId: string) {
  return useQuery<{ items: EventoContrato[] }>({
    queryKey: eventosKeys.byLicitacion(licitacionId),
    queryFn: () => fetchWithAuth(`/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/eventos`),
    staleTime: 5 * 60 * 1000,
    // El fallo se pinta en el bloque (`PanelError`): sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });
}
