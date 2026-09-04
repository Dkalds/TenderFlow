/**
 * Seguimiento de empresas — una sola implementación.
 *
 * La consulta y la mutación de `["watchlist-empresas"]` estaban copiadas en
 * tres sitios (`competidores/page.tsx`, `empresas/page.tsx` y
 * `components/competitors/company-profile.tsx`) con la misma clave y tres
 * variantes de la misma lógica: dos aceptaban una lista de ids y una un id
 * suelto, y sólo una de las tres invalidaba con `void`. Compartir la clave sin
 * compartir el código es lo que deja que una copia derive de las otras sin que
 * nada avise, así que aquí viven las dos.
 */
"use client";

import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { watchlistKeys } from "@/lib/query-keys";

interface EmpresaSeguida {
  empresa_id: number;
}

interface WatchlistEmpresasResponse {
  items: EmpresaSeguida[];
}

/** Empresas que el usuario sigue, como conjunto de ids listo para consultar. */
export function useEmpresasWatchlist() {
  const query = useQuery<WatchlistEmpresasResponse>({
    queryKey: watchlistKeys.empresas,
    queryFn: () => fetchWithAuth<WatchlistEmpresasResponse>("/api/v1/competitive/watchlist"),
    staleTime: 60 * 1000,
  });

  const watchedIds = useMemo(
    () => new Set((query.data?.items ?? []).map((item) => item.empresa_id)),
    [query.data],
  );

  return { ...query, watchedIds };
}

/** Variables de `toggle`: qué empresas y en qué estado están **ahora**. */
export interface ToggleEmpresaWatchVars {
  empresaIds: number[];
  /** `true` si ya se siguen: la mutación entonces deja de seguirlas. */
  watched: boolean;
}

/**
 * Alterna el seguimiento de una o varias empresas.
 *
 * Acepta siempre una lista: el perfil de empresa alterna el grupo de ids
 * equivalentes de una matriz (una empresa puede tener varios `empresa_id` tras
 * la deduplicación) y el listado alterna uno solo. Un solo contrato evita las
 * dos firmas que había.
 */
export function useToggleEmpresaWatch() {
  const queryClient = useQueryClient();
  return useMutation<unknown, unknown, ToggleEmpresaWatchVars>({
    mutationFn: ({ empresaIds, watched }) =>
      Promise.all(
        empresaIds.map((id) =>
          watched
            ? apiMutate("DELETE", `/api/v1/competitive/watchlist/${id}`)
            : apiMutate("POST", "/api/v1/competitive/watchlist", {
                empresa_id: id,
                frequency: "daily",
              }),
        ),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: watchlistKeys.empresas });
    },
  });
}
