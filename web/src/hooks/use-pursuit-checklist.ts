"use client";

/**
 * Checklist go/no-go de una oportunidad (S2.3).
 *
 * `GET /pursuits/{id}/checklist` contrasta la ficha del pliego con el perfil de
 * capacidad declarado en `/equipo → Organización` y devuelve, por familia, un
 * veredicto `cumple | no_cumple | desconocido` con la cita del pliego que lo
 * sostiene. Todo el criterio vive en `services/go_no_go.py`: aquí no se decide
 * nada ni se recalcula nada (ADR-014).
 *
 * La organización viaja como parámetro igual que en `usePursuit`: el backend la
 * resuelve sola si se omite, pero el contraste se hace contra el perfil de la
 * organización activa y la clave de caché tiene que distinguirlas.
 */

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import type { Schemas } from "@/lib/api-types";
import { pursuitKeys } from "@/lib/query-keys";

export type GoNoGoChecklist = Schemas["GoNoGoChecklist"];
export type ChecklistFamiliaResultado = Schemas["ChecklistFamiliaResultado"];
export type ChecklistItem = Schemas["ChecklistItem"];
export type ChecklistVeredicto = ChecklistItem["veredicto"];

export function usePursuitChecklist(pursuitId: number | string | null) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...pursuitKeys.checklist(pursuitId ?? ""), organizationId],
    queryFn: () => {
      const params = new URLSearchParams();
      if (organizationId != null) params.set("organization_id", String(organizationId));
      const query = params.toString();
      return fetchWithAuth<GoNoGoChecklist>(
        `/api/v1/pursuits/${encodeURIComponent(String(pursuitId))}/checklist${
          query ? `?${query}` : ""
        }`,
      );
    },
    enabled: pursuitId != null && pursuitId !== "",
    // La ficha del pliego no cambia entre pestañas: la evaluación se sella una
    // vez por versión de ficha, así que volver a pedirla en cada foco solo
    // añadiría eventos `checklist_evaluated` sin información nueva.
    staleTime: 5 * 60_000,
  });
}
