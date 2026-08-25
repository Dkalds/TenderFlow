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

  // La ruta puede traer ya su propia query (`…/trends?group_by=month`), así que
  // los filtros se FUSIONAN sobre ella en vez de concatenarse detrás de un
  // segundo `?`. Concatenar producía `…/trends?group_by=month?tecnologia=SAP`,
  // que el backend lee como `group_by="month?tecnologia=SAP"` y su
  // `Literal["month","week","day"]` rechaza con 422: la pantalla entera se caía
  // en cuanto el ámbito tenía un filtro (`/mercado?tecnologia=SAP`).
  const [path, baseQuery = ""] = url.split("?");
  const search = new URLSearchParams(baseQuery);
  // Los params explícitos ganan a los literales de la ruta, misma precedencia
  // que `extraParams` ← `filterParams` de la línea de arriba.
  for (const [key, value] of Object.entries(merged)) search.set(key, value);
  const queryString = search.toString();
  const fullUrl = queryString ? `${path}?${queryString}` : path;

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
