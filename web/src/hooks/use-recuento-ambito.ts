"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { fetchWithAuth, type ApiGetResult } from "@/lib/api-client";
import { analyticsKeys } from "@/lib/query-keys";

type Overview = ApiGetResult<"/api/v1/analytics/overview">;

/**
 * Recuento del ámbito de la barra (`GET /analytics/overview`) con los filtros
 * que aplican a la página.
 *
 * Clave propia (`analyticsKeys.overview`), no la de los `useFilteredQuery` de
 * las pantallas: la barra vive en el layout y, con la misma clave, le quitaba
 * al Resumen el dato prefetcheado en el render de servidor (el porqué, en
 * `lib/query-keys.ts`). Compartirla tampoco ahorraba la petición allí: medido
 * el 2026-11-26, las de /resumen salían todas de la barra con las dos claves.
 * Sí la comparte con /mercado › órganos, que no prefetchea. No usa
 * `useFilteredQuery` porque siempre fusiona `useFilterParams()` completo, que
 * es justo lo que la barra recorta.
 */
export function useRecuentoAmbito(params: Record<string, string>, enabled: boolean) {
  return useQuery<Overview>({
    queryKey: analyticsKeys.overview(params),
    queryFn: ({ signal }) => {
      const search = new URLSearchParams(params).toString();
      return fetchWithAuth<Overview>(
        search ? `/api/v1/analytics/overview?${search}` : "/api/v1/analytics/overview",
        { signal },
      );
    },
    enabled,
    // Mismo comportamiento que `useFilteredQuery`: al cambiar el ámbito se
    // mantiene el número anterior en vez de parpadear a «—».
    placeholderData: keepPreviousData,
  });
}
