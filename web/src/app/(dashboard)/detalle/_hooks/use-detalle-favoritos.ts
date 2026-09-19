"use client";

import { useEffect, useState } from "react";
import { useSeguimiento } from "@/hooks/use-seguimiento";
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
 *
 * Seguir pasa por `useSeguimiento`, lo mismo que la estrella de cada fila
 * (`SeguirBoton`): el atajo «S» y la acción en bloque no pueden comportarse
 * distinto que el botón (ADR-031 §C).
 */
export function useDetalleFavoritos(): DetalleFavoritos {
  const seguimiento = useSeguimiento("licitacion");
  const { seguir, alternar } = seguimiento;

  const [lastViewed] = useState(() => getJSON<number>(LAST_VIEWED_KEY, 0));
  useEffect(() => {
    setJSON(LAST_VIEWED_KEY, Date.now());
  }, []);

  // Migración one-shot: favoritos que vivían sólo en localStorage pasan al
  // servidor (ADR-014 §2); la clave se borra tras migrar para no repetir.
  useEffect(() => {
    const legacy = getWatchlist();
    if (legacy.length === 0) return;
    legacy.forEach((id) => seguir(id));
    removeStored(WATCHLIST_KEY);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- migración única al montar
  }, []);

  return {
    watchedIds: seguimiento.ids,
    lastViewed,
    toggleFavorite: (id: string) => {
      alternar(id);
    },
    seguir,
  };
}
