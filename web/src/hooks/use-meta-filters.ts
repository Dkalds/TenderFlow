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
import type { MetaFilters } from "@/lib/api-types";
import { metaKeys } from "@/lib/query-keys";

/**
 * El contrato generado, no una copia a mano: la copia se quedó en las cuatro
 * listas de 2026-08 y no veía los catálogos de procedimiento, tramitación y
 * tipo de contrato (F1.7) que la misma respuesta ya traía.
 */
export type { MetaFilters };

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
