import { useQuery, keepPreviousData, type UseQueryOptions } from "@tanstack/react-query";
import { useFilterParams } from "@/lib/filters";
import { fetchWithAuth } from "@/lib/api-client";
import { filteredQueryKey, filteredQueryUrl, mergeFilteredParams } from "@/lib/filtered-query";

/**
 * Data-fetching hook that automatically includes global filter params
 * in the query key and URL.
 *
 * Uses fetchWithAuth from api-client.ts for centralized auth handling
 * (401 redirect, error formatting). No puede pasar por `apiGet`: la ruta es un
 * parámetro en runtime, no un literal del esquema, así que quien tipa la
 * respuesta es el llamante vía `T`. Los call sites viven en `src/app/**` y
 * `src/components/**` — olas siguientes de la migración.
 *
 * La petición lleva el `signal` de React Query. Cambiar un filtro deja la
 * consulta anterior sin observadores y React Query la aborta: en Resumen son
 * ~7 agregados sobre el histórico entero que, sin cancelar, la API seguía
 * calculando para nadie. El aborto no llega a error visible (ni aviso, ni
 * reintento): React Query devuelve la consulta cancelada a su estado previo en
 * silencio, sin pasar por el `onError` de la caché.
 *
 * @param baseKey - React Query cache key
 * @param url - API endpoint path (without query string)
 * @param options - Additional React Query options
 * @param extraParams - Additional params merged with global filters
 * @param isRealtime - If true, does NOT use keepPreviousData (shows loading
 *   skeleton instead of stale data during refetch)
 * @param overrideParams - Params that win over the global filters (see
 *   `mergeFilteredParams`): only for params that identify the resource.
 */
export function useFilteredQuery<T>(
  baseKey: string[],
  url: string,
  options?: Omit<UseQueryOptions<T>, "queryKey" | "queryFn">,
  extraParams?: Record<string, string>,
  isRealtime?: boolean,
  overrideParams?: Record<string, string>,
) {
  const filterParams = useFilterParams();
  const merged = mergeFilteredParams(filterParams, extraParams, overrideParams);
  const fullUrl = filteredQueryUrl(url, merged);

  return useQuery<T>({
    // Clave y URL salen de `lib/filtered-query.ts`, el mismo módulo con el que
    // el prefetch en servidor construye las suyas.
    queryKey: filteredQueryKey(baseKey, url, merged),
    queryFn: ({ signal }) => fetchWithAuth<T>(fullUrl, { signal }),
    ...(isRealtime ? {} : { placeholderData: keepPreviousData }),
    ...options,
  });
}
