"use client";

/**
 * Pesos propuestos a partir de lo ganado y lo perdido (S3.3).
 *
 * `GET /pursuits/weights-proposal` compara, dimensión a dimensión, el desglose
 * sellado de las oportunidades ganadas frente al de las perdidas y propone una
 * redistribución que sigue sumando 100. Con menos de `minimo_cierres` cierres
 * contesta `estado: "insuficiente"` y **no manda propuesta**: la pantalla dice
 * cuánto falta, no enseña un ajuste con una advertencia al lado.
 *
 * Aplicarla es un POST sin cuerpo a propósito (`.../apply`): el backend
 * recalcula la propuesta y escribe exactamente esa, así que lo aplicado y lo
 * que se enseñó no pueden divergir. Queda en `audit_log`.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiMutate } from "@/lib/api-client";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import type { Schemas } from "@/lib/api-types";
import { perfilKeys, pursuitKeys, radarKeys } from "@/lib/query-keys";

export type PesosPropuestos = Schemas["PesosPropuestos"];
export type PesoPropuestoDimension = Schemas["PesoPropuestoDimension"];
export type PesosPropuestosAplicados = Schemas["PesosPropuestosAplicados"];

export function useWeightsProposal() {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...pursuitKeys.weightsProposal, organizationId],
    queryFn: () =>
      apiGet("/api/v1/pursuits/weights-proposal", {
        params: { query: { organization_id: organizationId ?? undefined } },
      }),
    staleTime: 60_000,
  });
}

export function useApplyWeightsProposal() {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: () => {
      const params = new URLSearchParams();
      if (organizationId != null) params.set("organization_id", String(organizationId));
      const query = params.toString();
      return apiMutate<PesosPropuestosAplicados>(
        "POST",
        `/api/v1/pursuits/weights-proposal/apply${query ? `?${query}` : ""}`,
      );
    },
    // El perfil acaba de cambiar, así que el formulario de la propia página, la
    // propuesta (que ahora parte de otros pesos actuales) y el ranking del
    // Radar dejan de ser válidos a la vez.
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: perfilKeys.me }),
        queryClient.invalidateQueries({ queryKey: pursuitKeys.weightsProposal }),
        queryClient.invalidateQueries({ queryKey: radarKeys.scoring }),
      ]),
  });
}
