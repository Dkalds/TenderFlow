import { useQuery, keepPreviousData, type UseQueryOptions } from "@tanstack/react-query";
import { useFilterParams } from "@/lib/filters";
import { fetchWithAuth } from "@/lib/api-client";

/**
 * Data-fetching hook that automatically includes global filter params
 * in the query key and URL.
 *
 * Uses fetchWithAuth from api-client.ts for centralized auth handling
 * (401 redirect, error formatting).
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
    queryKey: [...baseKey, filterParams],
    queryFn: () => fetchWithAuth<T>(fullUrl),
    ...(isRealtime ? {} : { placeholderData: keepPreviousData }),
    ...options,
  });
}
