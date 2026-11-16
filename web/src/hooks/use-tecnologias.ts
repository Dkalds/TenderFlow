"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth, type ApiGetResult } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { tecnologiasKeys } from "@/lib/query-keys";

type TecnologiasResult = ApiGetResult<"/api/v1/licitaciones/{id_externo}/tecnologias">;

/** Tecnologías detectadas en una licitación (título, ML y pliego) con su evidencia. */
export function useTecnologias(licitacionId: string) {
  return useQuery({
    queryKey: tecnologiasKeys.byLicitacion(licitacionId),
    queryFn: () =>
      fetchWithAuth<TecnologiasResult>(`/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/tecnologias`),
    staleTime: 5 * 60 * 1000,
    // El fallo se pinta en el bloque (`PanelError`): sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });
}
