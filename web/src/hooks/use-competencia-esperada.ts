"use client";

import { useQuery } from "@tanstack/react-query";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import { fetchWithAuth } from "@/lib/api-client";
import type { CompetenciaEsperada } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { competitiveKeys } from "@/lib/query-keys";

export type { CompetenciaEsperada };

/**
 * Competencia esperada de un expediente: cuántos se presentarán, quién lo
 * tiene hoy y contra quién se compite, sobre el segmento del propio expediente.
 *
 * Un solo hook para los cuatro sitios que la leen —el bloque de las fichas, los
 * escenarios de precio (que pueden acotar su cohorte a esa competencia) y el
 * simulador (que ofrece la baja del incumbente como rival)—: misma clave, una
 * sola petición.
 *
 * Espera a conocer la organización activa: la respuesta saca a la propia
 * organización de la lista de rivales, y pedirla con la personal enseñaría a
 * tu empresa como competidora de sí misma.
 */
export function useCompetenciaEsperada(licitacionId: string | null | undefined) {
  const organizationId = useActiveOrganizationId();
  return useQuery<CompetenciaEsperada>({
    queryKey: competitiveKeys.competenciaEsperada(licitacionId ?? "", organizationId),
    queryFn: ({ signal }) => {
      const query = organizationId != null ? `?organization_id=${organizationId}` : "";
      return fetchWithAuth<CompetenciaEsperada>(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId!)}/competencia-esperada${query}`,
        { signal },
      );
    },
    enabled: Boolean(licitacionId) && organizacionResuelta(organizationId),
    staleTime: 5 * 60_000,
    // El fallo se dice en el bloque: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });
}
