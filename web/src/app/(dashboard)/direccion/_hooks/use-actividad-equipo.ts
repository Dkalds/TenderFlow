"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { organizacionResuelta, type OrganizacionActiva } from "@/hooks/use-organization";
import { apiGet } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { pursuitKeys } from "@/lib/query-keys";

const PAGINA = 50;

/** Feed de actividad del equipo, paginado por el cursor del backend (`antes_de_id`). */
export function useActividadEquipo(organizationId: OrganizacionActiva, usuario: number | null) {
  return useInfiniteQuery({
    queryKey: pursuitKeys.actividad(organizationId, usuario),
    queryFn: ({ pageParam }) =>
      apiGet("/api/v1/pursuits/actividad", {
        params: {
          query: {
            organization_id: organizationId ?? undefined,
            usuario: usuario ?? undefined,
            antes_de_id: pageParam ?? undefined,
            limit: PAGINA,
          },
        },
      }),
    initialPageParam: null as number | null,
    getNextPageParam: (pagina) => pagina.siguiente_cursor ?? undefined,
    // La actividad es la del equipo: sin saber de cuál, el feed sale con la de
    // la organización personal y se reemplaza a la vista del usuario.
    enabled: organizacionResuelta(organizationId),
    // El fallo se pinta en el feed (`PanelError`): sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });
}
