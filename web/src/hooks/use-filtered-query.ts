import { useQuery, keepPreviousData, type UseQueryOptions } from "@tanstack/react-query";
import { useFilterParams } from "@/lib/filters";
import { fetchWithAuth } from "@/lib/api-client";

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
 * @param baseKey - React Query cache key
 * @param url - API endpoint path (without query string)
 * @param options - Additional React Query options
 * @param extraParams - Additional params merged with global filters
 * @param isRealtime - If true, does NOT use keepPreviousData (shows loading
 *   skeleton instead of stale data during refetch)
 */
export function useFilteredQuery<T>(
  baseKey: string[],
  url: string,
  options?: Omit<UseQueryOptions<T>, "queryKey" | "queryFn">,
  extraParams?: Record<string, string>,
  isRealtime?: boolean,
) {
  const filterParams = useFilterParams();
  const merged = { ...extraParams, ...filterParams };

  const queryString = new URLSearchParams(merged).toString();
  const fullUrl = queryString ? `${url}?${queryString}` : url;

  return useQuery<T>({
    // La URL y los params fusionados forman parte de la key: dos endpoints (o el
    // mismo con distintos `extraParams`) comparten `baseKey` y colisionarían en
    // caché de otro modo. `baseKey` sigue siendo el prefijo, así que las
    // invalidaciones por prefijo (`invalidateQueries({ queryKey: baseKey })`)
    // siguen alcanzando todas las variantes.
    queryKey: [...baseKey, url, merged],
    queryFn: () => fetchWithAuth<T>(fullUrl),
    ...(isRealtime ? {} : { placeholderData: keepPreviousData }),
    ...options,
  });
}
