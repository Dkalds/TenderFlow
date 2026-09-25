"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { analyticsKeys, licitacionKeys, licitacionesKeys } from "@/lib/query-keys";
import type { LicitacionesCursorPage } from "@/lib/api-types";
import type { LicitacionDetail } from "@/components/detail-panel";
import {
  conTotalConocido,
  conjuntoDelListado,
  pageIdsOf,
  type ScoringItem,
  type ScoringResponse,
  type TotalConocido,
} from "./detalle-table-model";

/**
 * Las tres consultas de /detalle, en un sitio.
 *
 * Son las únicas puertas a la API de esta pantalla (invariante §3.8): listado
 * paginado, scoring alineado a la página visible y ficha del expediente
 * abierto. Ninguna de las tres deriva analítica en cliente — el score y su
 * desglose vienen calculados de servidor (ADR-014).
 */

/**
 * Página del listado por cursor (`GET /licitaciones/cursor`). Sustituye al
 * listado por offset, que se retira (RFC 2026-09-06): mismos filtros y mismos
 * órdenes, `next_cursor` en vez de `offset` y `total` porque la primera página
 * pide `with_total`.
 */
export type LicitacionesResponse = LicitacionesCursorPage;

export interface DetalleQueries {
  /**
   * La página visible. Su `total` es el de la primera página de su conjunto de
   * filtros y orden, aunque ésta no lo haya pedido (ver `buildQueryParams`).
   */
  data: LicitacionesResponse | undefined;
  isLoading: boolean;
  isFetching: boolean;
  /**
   * `true` mientras se enseña la página anterior (`placeholderData`) y la
   * pedida no ha llegado. El `next_cursor` de ese dato es de la página
   * anterior: no se puede apuntar como el de la actual.
   */
  isPlaceholderData: boolean;
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
  const { data, isLoading, error, isFetching, isPlaceholderData, refetch } = useQuery({
    queryKey: licitacionesKeys.list(queryParams),
    queryFn: ({ signal }) =>
      fetchWithAuth<LicitacionesResponse>(`/api/v1/licitaciones/cursor?${new URLSearchParams(queryParams)}`, {
        signal,
      }),
    staleTime: 30_000,
    placeholderData: (previous) => previous,
    retry: 2,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10000),
  });

  // Sólo la primera página trae `total`; se recuerda por conjunto para el «de
  // N» de las siguientes. Ajuste durante el render, el patrón que React
  // documenta para derivar estado de lo recibido: no pinta un pie sin total
  // para corregirlo después. Nunca desde datos de relleno, que pueden ser de
  // otro conjunto.
  const conjunto = conjuntoDelListado(queryParams);
  const [conocido, setConocido] = useState<TotalConocido | null>(null);
  const totalRecibido = isPlaceholderData ? null : data?.total;
  if (totalRecibido != null && (conocido?.conjunto !== conjunto || conocido.total !== totalRecibido)) {
    setConocido({ conjunto, total: totalRecibido });
  }
  const pagina = useMemo(
    () => conTotalConocido(data, conjunto, conocido, isPlaceholderData),
    [data, conjunto, conocido, isPlaceholderData],
  );

  // Scoring alineado a la página: se pide el score exacto de las filas visibles
  // (sus id_externo), no un top-500 global disjunto del orden y del filtro.
  //
  // Va detrás del listado y no en paralelo porque depende de él: el modo
  // alineado de `GET /analytics/scoring` sólo acepta `ids`, no los filtros ni
  // el cursor del listado, y sin ellos lo único que ofrece es un top-N por
  // score, que no es esta página ni este orden.
  const pageIds = useMemo(() => pageIdsOf(data?.items), [data]);

  const { data: scoring } = useQuery({
    queryKey: analyticsKeys.scoringBatch(pageIds),
    queryFn: ({ signal }) =>
      fetchWithAuth<ScoringResponse>(`/api/v1/analytics/scoring?${new URLSearchParams({ ids: pageIds.join(",") })}`, {
        signal,
      }),
    enabled: pageIds.length > 0,
    staleTime: 5 * 60_000,
    placeholderData: (previous) => previous,
  });

  const { data: detailData } = useQuery({
    queryKey: licitacionKeys.detail(detailId ?? ""),
    queryFn: ({ signal }) =>
      fetchWithAuth<LicitacionDetail>(`/api/v1/licitaciones/${encodeURIComponent(detailId!)}`, { signal }),
    enabled: !!detailId,
  });

  return { data: pagina, isLoading, isFetching, isPlaceholderData, error, refetch, scoring, detailData };
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
