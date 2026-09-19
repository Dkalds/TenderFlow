"use client";

import { useQuery } from "@tanstack/react-query";
import { ApiError, fetchWithAuth } from "@/lib/api-client";
import type { PaginaDocumento } from "@/lib/api-types";
import { paginaKeys } from "@/lib/query-keys";

export type { PaginaDocumento };

export interface PaginaSolicitada {
  documentoId: number;
  pagina: number;
  /** Offsets absolutos de la cita (`EvidenceRef.start_offset`/`end_offset`). */
  inicio?: number | null;
  fin?: number | null;
}

/**
 * F2.5 — el texto de una página del pliego y dónde cae la cita.
 *
 * Los offsets sólo se mandan en la página de la cita: al navegar a otra, la
 * cita ya no está ahí y pedirla resaltada devolvería un aviso de offsets
 * incoherentes que no es culpa de nadie. Quien llama decide cuándo pasarlos.
 *
 * El 404 (página sin texto extraído) no se reintenta: es una respuesta.
 */
export function usePaginaDocumento(licitacionId: string, solicitud: PaginaSolicitada | null) {
  const inicio = solicitud?.inicio ?? null;
  const fin = solicitud?.fin ?? null;
  return useQuery({
    queryKey: paginaKeys.detail(
      licitacionId,
      solicitud?.documentoId ?? 0,
      solicitud?.pagina ?? 0,
      inicio,
      fin,
    ),
    queryFn: () => {
      const query = new URLSearchParams();
      if (inicio != null) query.set("inicio", String(inicio));
      if (fin != null) query.set("fin", String(fin));
      const qs = query.toString();
      return fetchWithAuth<PaginaDocumento>(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/documentos/` +
          `${solicitud!.documentoId}/paginas/${solicitud!.pagina}${qs ? `?${qs}` : ""}`,
      );
    },
    enabled: Boolean(licitacionId && solicitud),
    staleTime: 10 * 60_000,
    retry: (intento, error) => !(error instanceof ApiError && error.status === 404) && intento < 2,
    placeholderData: (anterior) => anterior,
  });
}
