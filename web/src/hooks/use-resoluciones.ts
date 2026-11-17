"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { resolucionesKeys } from "@/lib/query-keys";

/** Resoluciones TACRC vinculadas a una licitación: las leen el bloque «Recursos» y la chapa «Recurrido». */
export function useResoluciones(licitacionId: string) {
  return useQuery({
    queryKey: resolucionesKeys.byLicitacion(licitacionId),
    queryFn: ({ signal }) =>
      apiGet("/api/v1/resoluciones", { params: { query: { licitacion_id: licitacionId } }, signal }),
    staleTime: 5 * 60 * 1000,
    // El fallo lo dicen el bloque y la chapa, cada uno en su sitio: sin toast.
    meta: META_ERROR_EN_LINEA,
  });
}
