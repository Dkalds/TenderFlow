import { useQuery, type UseQueryOptions } from "@tanstack/react-query";
import { useFilterParams } from "@/lib/filters";

/**
 * useQuery wrapper that automatically includes global filter params.
 * The queryKey automatically includes the filter params for proper cache invalidation.
 */
export function useFilteredQuery<T>(
  baseKey: string[],
  url: string,
  options?: Omit<UseQueryOptions<T>, "queryKey" | "queryFn">,
) {
  const filterParams = useFilterParams();

  const queryString = new URLSearchParams(filterParams).toString();
  const fullUrl = queryString ? `${url}?${queryString}` : url;

  return useQuery<T>({
    queryKey: [...baseKey, filterParams],
    queryFn: async () => {
      const res = await fetch(fullUrl, { credentials: "include" });
      if (!res.ok) {
        if (res.status === 401 && typeof window !== "undefined") {
          window.location.href = "/login";
        }
        throw new Error(`API error: ${res.status}`);
      }
      return res.json() as Promise<T>;
    },
    ...options,
  });
}
