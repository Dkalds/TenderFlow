"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { fetchWithAuth, type ApiGetResult } from "@/lib/api-client";
import { analyticsKeys } from "@/lib/query-keys";

type Overview = ApiGetResult<"/api/v1/analytics/overview">;

/**
 * Recuento del ámbito de la barra (`GET /analytics/overview`) con los filtros
 * que aplican a la página.
 *
 * Misma forma de clave que `useFilteredQuery` (`[...baseKey, url, params]`),
 * para que en las pantallas que consumen el ámbito entero comparta caché con el
 * resto de consumidores de `/analytics/overview` en vez de duplicar la
 * petición. No usa ese hook porque siempre fusiona `useFilterParams()`
 * completo, que es justo lo que la barra recorta.
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
