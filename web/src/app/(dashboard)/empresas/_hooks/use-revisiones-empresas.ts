"use client";

/**
 * Cola de matches dudosos del resolutor de empresas y su resolución.
 *
 * Resolver uno mueve tres cosas —la cola, el contador de cobertura y el propio
 * maestro—, así que se invalidan las tres claves y no solo la lista.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { empresasKeys } from "@/lib/query-keys";
import type { ReviewItem } from "../_lib/types";

export function useRevisionesEmpresas() {
  const queryClient = useQueryClient();

  const { data } = useQuery<{ items: ReviewItem[] }>({
    queryKey: empresasKeys.reviews,
    queryFn: () => fetchWithAuth("/api/v1/empresas/reviews?limit=20"),
  });

  const resolve = useMutation({
    mutationFn: ({ id, accept }: { id: number; accept: boolean }) =>
      apiMutate("POST", `/api/v1/empresas/reviews/${id}`, { accept }),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: empresasKeys.reviews });
      queryClient.invalidateQueries({ queryKey: empresasKeys.stats });
      queryClient.invalidateQueries({ queryKey: empresasKeys.all });
    },
  });

  return { items: data?.items ?? [], resolve };
}
