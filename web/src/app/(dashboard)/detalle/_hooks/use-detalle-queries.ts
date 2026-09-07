"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { analyticsKeys, licitacionKeys, licitacionesKeys } from "@/lib/query-keys";
import type { LicitacionSummary } from "@/lib/api-types";
import type { LicitacionDetail } from "@/components/detail-panel";
import { pageIdsOf, type ScoringItem, type ScoringResponse } from "./detalle-table-model";

/**
 * Las tres consultas de /detalle, en un sitio.
 *
 * Son las únicas puertas a la API de esta pantalla (invariante §3.8): listado
 * paginado, scoring alineado a la página visible y ficha del expediente
 * abierto. Ninguna de las tres deriva analítica en cliente — el score y su
 * desglose vienen calculados de servidor (ADR-014).
 */

export interface LicitacionesResponse {
  items: LicitacionSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface DetalleQueries {
  data: LicitacionesResponse | undefined;
  isLoading: boolean;
  isFetching: boolean;
  error: unknown;
  refetch: () => void;
  scoring: ScoringResponse | undefined;
  detailData: LicitacionDetail | undefined;
}

export function useDetalleQueries({
  queryParams,
  detailId,
}: {
  queryParams: Record<string, string>;
  detailId: string | null;
}): DetalleQueries {
  const { data, isLoading, error, isFetching, refetch } = useQuery({
    queryKey: licitacionesKeys.list(queryParams),
    queryFn: ({ signal }) =>
      fetchWithAuth<LicitacionesResponse>(
        `/api/v1/licitaciones?${new URLSearchParams(queryParams)}`,
        { signal },
      ),
    staleTime: 30_000,
    placeholderData: (previous) => previous,
    retry: 2,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10000),
  });

  // Scoring alineado a la página: se pide el score exacto de las filas visibles
  // (sus id_externo), no un top-500 global disjunto del orden y del filtro.
  const pageIds = useMemo(() => pageIdsOf(data?.items), [data]);

  const { data: scoring } = useQuery({
    queryKey: analyticsKeys.scoringBatch(pageIds),
    queryFn: ({ signal }) =>
      fetchWithAuth<ScoringResponse>(
        `/api/v1/analytics/scoring?${new URLSearchParams({ ids: pageIds.join(",") })}`,
        { signal },
      ),
    enabled: pageIds.length > 0,
    staleTime: 5 * 60_000,
    placeholderData: (previous) => previous,
  });

  const { data: detailData } = useQuery({
    queryKey: licitacionKeys.detail(detailId ?? ""),
    queryFn: () =>
      fetchWithAuth<LicitacionDetail>(`/api/v1/licitaciones/${encodeURIComponent(detailId!)}`),
    enabled: !!detailId,
  });

  return { data, isLoading, isFetching, error, refetch, scoring, detailData };
}

/**
 * La ficha con el score que ya tiene la tabla.
 *
 * `GET /licitaciones/{id}` no devuelve puntuación: sin esta mezcla el inspector
 * mostraría «—» justo en la fila cuyo score el usuario acaba de leer en la
 * tabla.
 */
export function useDetailWithScore(
  detailData: LicitacionDetail | undefined,
  scoreMap: Map<string, ScoringItem>,
): LicitacionDetail | null {
  return useMemo<LicitacionDetail | null>(() => {
    if (!detailData) return null;
    const scored = scoreMap.get(detailData.id_externo);
    return {
      ...detailData,
      score: scored?.score,
      band: scored?.band ?? null,
      score_desglose: scored?.desglose,
    } as LicitacionDetail;
  }, [detailData, scoreMap]);
}
