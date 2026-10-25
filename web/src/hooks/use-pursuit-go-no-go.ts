"use client";

/**
 * Matriz go/no-go de una oportunidad (C6.4, D30) — `GET|PUT /pursuits/{id}/go-no-go`.
 *
 * El backend puntúa cinco criterios de 1 a 5, pondera con los pesos de la
 * organización y recomienda `go` o `no_go` según el umbral; marca también si la
 * decisión ya tomada lo contradice (`discrepa`). Todo eso llega calculado
 * (`services/go_no_go_puntuacion.py`): aquí no se suma ni se pondera nada
 * (ADR-014), y los criterios, sus etiquetas y cuál va invertido salen de la
 * respuesta, así que uno nuevo aparece solo.
 *
 * La organización viaja como parámetro igual que en `usePursuitChecklist`: la
 * ponderación es la de la organización activa y la clave de caché tiene que
 * distinguirlas. Por lo mismo, la consulta espera a saber cuál es.
 *
 * Los pesos se cambian en Equipo → Organización: `useGuardarPesosGoNoGo`
 * invalida `pursuitKeys.goNoGoTodas`, así que la ficha vuelve a pedir su
 * puntuación en lugar de enseñar un total calculado con los pesos de antes.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import type { Schemas } from "@/lib/api-types";
import { pursuitKeys } from "@/lib/query-keys";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

export type PuntuacionGoNoGo = Schemas["GoNoGoScoreOut"];
export type CriterioPuntuado = Schemas["GoNoGoCriterioOut"];
export type PuntuarCriterioInput = Schemas["GoNoGoScoreIn"];

function ruta(pursuitId: number | string, organizationId: number | null | undefined): string {
  const base = `/api/v1/pursuits/${encodeURIComponent(String(pursuitId))}/go-no-go`;
  return organizationId != null ? `${base}?organization_id=${organizationId}` : base;
}

export function usePursuitGoNoGo(pursuitId: number | string | null) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...pursuitKeys.goNoGo(pursuitId ?? ""), organizationId],
    queryFn: () => fetchWithAuth<PuntuacionGoNoGo>(ruta(pursuitId!, organizationId)),
    enabled: pursuitId != null && pursuitId !== "" && organizacionResuelta(organizationId),
    staleTime: 30_000,
    meta: META_ERROR_EN_LINEA,
  });
}

/**
 * Puntúa un criterio. La respuesta es la matriz entera, ya recalculada, y se
 * escribe en la caché tal cual: el total y la recomendación son los del
 * servidor, no los que el cliente podría deducir.
 */
export function usePuntuarCriterio(pursuitId: number) {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    meta: { errorTitle: "No se pudo guardar la puntuación" },
    mutationFn: (entrada: PuntuarCriterioInput) =>
      apiMutate<PuntuacionGoNoGo>("PUT", ruta(pursuitId, organizationId), entrada),
    onSuccess: (puntuacion) => {
      queryClient.setQueryData([...pursuitKeys.goNoGo(pursuitId), organizationId], puntuacion);
    },
  });
}
