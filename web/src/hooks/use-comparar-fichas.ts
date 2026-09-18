"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type { CeldaComparacion, ComparacionFichas, FilaComparacion } from "@/lib/api-types";
import { comparacionKeys } from "@/lib/query-keys";

export type { CeldaComparacion, ComparacionFichas, FilaComparacion };

/** Tope de la API (`MAX_EXPEDIENTES_COMPARAR`): tres columnas se leen, cuatro no. */
export const MAX_COMPARAR = 3;

/**
 * F2.8 — las fichas de dos o tres expedientes, familia a familia.
 *
 * Es un `POST` en la API porque la lista de ids viaja en el cuerpo, pero no
 * tiene efectos ni coste de LLM (la comparación es determinista), así que se
 * lee como una query: se cachea por la lista **ordenada como la pidió el
 * usuario**, que es el orden de las columnas.
 */
export function useCompararFichas(ids: readonly string[]) {
  const validos = ids.length >= 2 && ids.length <= MAX_COMPARAR;
  return useQuery({
    queryKey: comparacionKeys.fichas(ids),
    queryFn: () =>
      fetchWithAuth<ComparacionFichas>("/api/v1/licitaciones/comparar", {
        method: "POST",
        body: JSON.stringify({ ids }),
      }),
    enabled: validos,
    staleTime: 5 * 60_000,
  });
}
