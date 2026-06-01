import { useQuery, keepPreviousData, type UseQueryOptions } from "@tanstack/react-query";
import { useFilterParams } from "@/lib/filters";
import { ApiError } from "@/lib/api-client";

/**
 * Data-fetching hook that automatically includes global filter params
 * in the query key and URL. Uses the centralized ApiError class.
 *
 * The 401 redirect is handled globally by the api-client middleware,
 * but we also handle it here for raw-fetch calls during the transition
 * to the fully typed openapi-fetch client.
 */
export function useFilteredQuery<T>(
  baseKey: string[],
  url: string,
  options?: Omit<UseQueryOptions<T>, "queryKey" | "queryFn">,
  extraParams?: Record<string, string>,
) {
  const filterParams = useFilterParams();
  const merged = { ...extraParams, ...filterParams };

  const queryString = new URLSearchParams(merged).toString();
  const fullUrl = queryString ? `${url}?${queryString}` : url;

  return useQuery<T>({
    queryKey: [...baseKey, filterParams],
    queryFn: async () => {
      const res = await fetch(fullUrl, { credentials: "include" });
      if (!res.ok) {
        if (res.status === 401 && typeof window !== "undefined") {
          window.location.href = "/login";
        }
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new ApiError(res.status, body.detail ?? `API error: ${res.status}`);
      }
      return res.json() as Promise<T>;
    },
    placeholderData: keepPreviousData,
    ...options,
  });
}
