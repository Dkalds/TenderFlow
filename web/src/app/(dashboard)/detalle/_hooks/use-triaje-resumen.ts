"use client";

import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { parseAsString, useQueryState } from "nuqs";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import { fetchWithAuth } from "@/lib/api-client";
import { analyticsKeys } from "@/lib/query-keys";
import { PARAMETRO_DESDE, PARAMETRO_INTENCION, intencionDeTriaje } from "../_lib/triaje-resumen";
import { parametrosScoring, type ScoringResponse } from "./detalle-table-model";

/**
 * La puntuación de una sola licitación con el perfil de la organización
 * activa (`GET /analytics/scoring?ids=`), o `null` si el scoring no la trae.
 */
export function usePuntuacionTriaje(idExterno: string) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: analyticsKeys.scoringBatch(organizationId, [idExterno]),
    queryFn: ({ signal }) =>
      fetchWithAuth<ScoringResponse>(`/api/v1/analytics/scoring?${parametrosScoring([idExterno], organizationId)}`, {
        signal,
      }),
    enabled: organizacionResuelta(organizationId),
    staleTime: 5 * 60_000,
    select: (respuesta) => respuesta.opportunities?.find((item) => item.id_externo === idExterno) ?? null,
  });
}

/**
 * La intención con la que se llegó desde el resumen diario
 * (`_lib/triaje-resumen.ts`), y cómo quitarla. Viaja en la URL y se quita con
 * `replace`, para que «atrás» no vuelva a ofrecer un triaje ya decidido.
 */
export function useTriajeResumen() {
  const [desde, setDesde] = useQueryState(PARAMETRO_DESDE, parseAsString.withOptions({ shallow: true }));
  const [intencionUrl, setIntencionUrl] = useQueryState(
    PARAMETRO_INTENCION,
    parseAsString.withOptions({ shallow: true }),
  );
  const cerrarTriaje = useCallback(() => {
    void setDesde(null, { history: "replace" });
    void setIntencionUrl(null, { history: "replace" });
  }, [setDesde, setIntencionUrl]);
  return { intencion: intencionDeTriaje(desde, intencionUrl), cerrarTriaje };
}
