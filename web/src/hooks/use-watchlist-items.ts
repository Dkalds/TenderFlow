/**
 * Watchlist items — server-side favorites for individual licitaciones.
 *
 * Persists the "starred" state of a licitación (by `id_externo`) via
 * `/api/v1/watchlist/items`, replacing the previous `localStorage`-only
 * approach (ADR-014 §2: user state is server-side).
 *
 * Add/remove mutations use optimistic updates against the `["watchlist-items"]`
 * cache so the star toggle feels instantaneous, with rollback on failure.
 */
"use client";

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import type { WatchlistFavoriteItem } from "@/lib/api-types";

// Del contrato OpenAPI (la ruta ya declara su DTO) — antes duplicado a mano.
export type WatchlistItem = WatchlistFavoriteItem;

const WATCHLIST_ITEMS_KEY = ["watchlist-items"] as const;

/** Build a placeholder item for optimistic inserts (enriched fields unknown yet). */
function buildOptimisticItem(idExterno: string): WatchlistItem {
  return {
    id: -Date.now(),
    id_externo: idExterno,
    created_at: new Date().toISOString(),
    organization_id: null,
    visibility: null,
    titulo: null,
    importe: null,
    estado: null,
    fecha_publicacion: null,
  };
}

interface MutationContext {
  previous: WatchlistItem[] | undefined;
}

async function cancelAndSnapshot(qc: QueryClient): Promise<WatchlistItem[] | undefined> {
  await qc.cancelQueries({ queryKey: WATCHLIST_ITEMS_KEY });
  return qc.getQueryData<WatchlistItem[]>(WATCHLIST_ITEMS_KEY);
}

export function useWatchlistItems() {
  return useQuery({
    queryKey: WATCHLIST_ITEMS_KEY,
    queryFn: () =>
      fetchWithAuth<{ items: WatchlistItem[] }>("/api/v1/watchlist/items").then(
        (r) => r.items,
      ),
    meta: { silent: true },
  });
}

export function useAddWatchlistItem() {
  const qc = useQueryClient();
  return useMutation<WatchlistItem, unknown, string, MutationContext>({
    mutationFn: (idExterno: string) =>
      apiMutate<WatchlistItem>("POST", "/api/v1/watchlist/items", { id_externo: idExterno }),
    onMutate: async (idExterno: string) => {
      const previous = await cancelAndSnapshot(qc);
      qc.setQueryData<WatchlistItem[]>(WATCHLIST_ITEMS_KEY, (old) => [
        buildOptimisticItem(idExterno),
        ...(old ?? []),
      ]);
      return { previous };
    },
    onError: (_err, _idExterno, ctx) => {
      qc.setQueryData(WATCHLIST_ITEMS_KEY, ctx?.previous);
      toast.error("No se pudo añadir a favoritos");
    },
    onSuccess: (created: WatchlistItem, idExterno: string) => {
      qc.setQueryData<WatchlistItem[]>(WATCHLIST_ITEMS_KEY, (old) =>
        (old ?? []).map((item) =>
          item.id_externo === idExterno && item.id < 0 ? created : item,
        ),
      );
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: WATCHLIST_ITEMS_KEY });
    },
  });
}

export function useRemoveWatchlistItem() {
  const qc = useQueryClient();
  return useMutation<void, unknown, string, MutationContext>({
    mutationFn: (idExterno: string) =>
      apiMutate<void>("DELETE", `/api/v1/watchlist/items/${idExterno}`),
    onMutate: async (idExterno: string) => {
      const previous = await cancelAndSnapshot(qc);
      qc.setQueryData<WatchlistItem[]>(WATCHLIST_ITEMS_KEY, (old) =>
        (old ?? []).filter((item) => item.id_externo !== idExterno),
      );
      return { previous };
    },
    onError: (_err, _idExterno, ctx) => {
      qc.setQueryData(WATCHLIST_ITEMS_KEY, ctx?.previous);
      toast.error("No se pudo quitar de favoritos");
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: WATCHLIST_ITEMS_KEY });
    },
  });
}

/** Whether `idExterno` is currently in the user's watchlist (for star icons). */
export function useIsWatchlisted(idExterno: string): boolean {
  const { data } = useWatchlistItems();
  return (data ?? []).some((item) => item.id_externo === idExterno);
}
