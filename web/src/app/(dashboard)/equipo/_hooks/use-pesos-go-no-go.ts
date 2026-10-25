"use client";

/**
 * Pesos de la matriz go/no-go de la organización (C6.4, D30).
 *
 * `GET/PUT /organizations/go-no-go/weights`. Los criterios, sus etiquetas, el
 * umbral y qué criterio va invertido los manda el backend
 * (`services/go_no_go_template.py`): aquí no se enumera ninguno, así que un
 * criterio nuevo aparece solo.
 *
 * Guardar escribe en el rastro de auditoría de la organización
 * (`go_no_go.weights_updated`): por eso se invalida la raíz común
 * `gobiernoOrgKeys.all` y no solo la clave de los pesos.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { gobiernoOrgKeys, pursuitKeys } from "@/lib/query-keys";

export type PesosGoNoGo = Schemas["GoNoGoWeightsOut"];

export function usePesosGoNoGo(organizationId: number) {
  return useQuery({
    queryKey: gobiernoOrgKeys.pesosGoNoGo(organizationId),
    queryFn: ({ signal }) =>
      apiGet("/api/v1/organizations/go-no-go/weights", {
        params: { query: { organization_id: organizationId } },
        signal,
      }),
    staleTime: 60_000,
    meta: META_ERROR_EN_LINEA,
  });
}

export function useGuardarPesosGoNoGo(organizationId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { errorTitle: "No se pudieron guardar los pesos" },
    mutationFn: (pesos: Record<string, number>) =>
      apiMutate<PesosGoNoGo>(
        "PUT",
        `/api/v1/organizations/go-no-go/weights?organization_id=${organizationId}`,
        { pesos } satisfies Schemas["GoNoGoWeightsIn"],
      ),
    onSuccess: (guardados) => {
      queryClient.setQueryData(gobiernoOrgKeys.pesosGoNoGo(organizationId), guardados);
      // Cambiar los pesos recalcula el total y la recomendación de la matriz de
      // cada oportunidad (`GET /pursuits/{id}/go-no-go`): sin invalidar su
      // prefijo, la ficha enseñaría una puntuación con los pesos de antes.
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: gobiernoOrgKeys.all }),
        queryClient.invalidateQueries({ queryKey: pursuitKeys.goNoGoTodas }),
      ]);
    },
  });
}
