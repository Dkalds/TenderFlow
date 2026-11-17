"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import { apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { analyticsKeys } from "@/lib/query-keys";

type NovedadesDesdeUltimaVisita = Schemas["NovedadesDesdeUltimaVisita"];
type VisitaMarcada = Schemas["VisitaMarcada"];

/** Lo que cambió en lo que sigues desde tu última visita (F5.4), para la organización activa. */
export function useDesdeUltimaVisita() {
  const organizationId = useActiveOrganizationId();
  return useQuery<NovedadesDesdeUltimaVisita>({
    queryKey: analyticsKeys.desdeUltimaVisita(organizationId),
    queryFn: () =>
      apiGet("/api/v1/analytics/resumen/desde-mi-ultima-visita", {
        params: { query: { organization_id: organizationId ?? undefined } },
      }),
    enabled: organizacionResuelta(organizationId),
    // El endpoint no cachea a propósito (es un diff por usuario y marca). En
    // cliente basta con no repetirlo en cada re-montaje de la pantalla.
    staleTime: 60_000,
  });
}

/**
 * «Marcar todo como visto»: mueve la marca y vuelve a pedir lo que cuelga de
 * ella — la banda y las licitaciones nuevas del mercado (`use-novedades.ts`:
 * la tarjeta «Nuevas» y los puntos de la tabla), que cuentan desde la misma
 * última visita.
 */
export function useMarcarVisto() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiMutate<VisitaMarcada>("POST", "/api/v1/analytics/resumen/desde-mi-ultima-visita/visto"),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: analyticsKeys.desdeUltimaVisitaTodas }),
        queryClient.invalidateQueries({ queryKey: analyticsKeys.novedades }),
      ]),
    meta: { errorTitle: "No se pudo marcar como visto" },
  });
}
