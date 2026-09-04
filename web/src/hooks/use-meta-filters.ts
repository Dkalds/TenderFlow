/**
 * Catálogos de filtros (`GET /meta/filters`) — una sola consulta.
 *
 * Se pedía dos veces con dos claves distintas para la misma respuesta:
 * `["meta-filters"]` en `layout/scope-bar.tsx` y `["meta-ccaas"]` en
 * `mi-watchlist/page.tsx`, esta última quedándose sólo con las CCAA. Dos
 * entradas de caché y dos peticiones al mismo endpoint.
 *
 * Quien sólo necesite una dimensión usa `useMetaCcaas`, que es la misma query
 * con un `select`: React Query cachea por clave, no por proyección, así que la
 * petición sigue siendo una.
 */
"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { metaKeys } from "@/lib/query-keys";

export interface MetaFilters {
  estado: string[];
  ccaa: string[];
  tecnologia: string[];
  cpv: string[];
}

export function useMetaFilters(enabled = true) {
  return useQuery<MetaFilters>({
    queryKey: metaKeys.filters,
    queryFn: () => fetchWithAuth<MetaFilters>("/api/v1/meta/filters"),
    staleTime: 5 * 60 * 1000,
    enabled,
  });
}

/** Sólo las CCAA del catálogo, sin una segunda petición. */
export function useMetaCcaas() {
  return useQuery<MetaFilters, Error, string[]>({
    queryKey: metaKeys.filters,
    queryFn: () => fetchWithAuth<MetaFilters>("/api/v1/meta/filters"),
    staleTime: 5 * 60 * 1000,
    select: (data) => data.ccaa ?? [],
  });
}
