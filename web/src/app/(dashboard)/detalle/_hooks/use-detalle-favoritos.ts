"use client";

import { useEffect, useMemo, useState } from "react";
import {
  useAddWatchlistItem,
  useRemoveWatchlistItem,
  useWatchlistItems,
} from "@/hooks/use-watchlist-items";
import { getJSON, setJSON, remove as removeStored } from "@/lib/storage";

const LAST_VIEWED_KEY = "detalle_last_viewed";
const WATCHLIST_KEY = "detalle_watchlist";

function getWatchlist(): string[] {
  // Lado lector de la migración one-shot a servidor: la clave se vacía tras
  // subirla. Corrige el patrón ADR-014 §2, no es una instancia de él.
  // fdi-allow:client-state
  return getJSON<string[]>(WATCHLIST_KEY, []);
}

export interface DetalleFavoritos {
  /** `id_externo` de lo que el usuario sigue, según el servidor. */
  watchedIds: Set<string>;
  /** Sello de la última visita: alimenta el punto de «nueva» de cada fila. */
  lastViewed: number;
  toggleFavorite: (id: string) => void;
  /** La barra de selección sigue en bloque; por eso el `mutate` se expone. */
  seguir: (id: string) => void;
}

/**
 * Favoritos de /detalle: estado de servidor, marca de última visita y la
 * migración one-shot de la lista que vivía en `localStorage`.
 *
 * El estado de usuario es server-side (ADR-014 §2). Lo único que queda en el
 * navegador es el sello de la última visita, que es preferencia de lectura y no
 * un dato del que dependa nadie más.
 */
export function useDetalleFavoritos(): DetalleFavoritos {
  const addWatchlistItem = useAddWatchlistItem();
  const removeWatchlistItem = useRemoveWatchlistItem();
  const { data: watched = [] } = useWatchlistItems();
  const watchedIds = useMemo(() => new Set(watched.map((item) => item.id_externo)), [watched]);

  const [lastViewed] = useState(() => getJSON<number>(LAST_VIEWED_KEY, 0));
  useEffect(() => {
    setJSON(LAST_VIEWED_KEY, Date.now());
  }, []);

  // Migración one-shot: favoritos que vivían sólo en localStorage pasan al
  // servidor (ADR-014 §2); la clave se borra tras migrar para no repetir.
  useEffect(() => {
    const legacy = getWatchlist();
    if (legacy.length === 0) return;
    legacy.forEach((id) => addWatchlistItem.mutate(id));
    removeStored(WATCHLIST_KEY);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- migración única al montar
  }, []);

  const toggleFavorite = (id: string) => {
    if (watchedIds.has(id)) removeWatchlistItem.mutate(id);
    else addWatchlistItem.mutate(id);
  };

  return {
    watchedIds,
    lastViewed,
    toggleFavorite,
    seguir: (id: string) => addWatchlistItem.mutate(id),
  };
}
