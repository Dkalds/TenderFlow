"use client";

/**
 * Las peticiones de «Mercado por segmento»: HHI por corte, cuota y baja de
 * referencia del segmento elegido, y bajas por grupo.
 *
 * Los cuatro endpoints existían (`api/routes/competitive.py`) y ninguna
 * pantalla los pedía. Responden lo mismo a cualquiera —el backend los cachea
 * 300 s compartidos—, así que aquí el `staleTime` es el mismo y la clave no
 * lleva organización.
 *
 * Qué filtros viajan lo decide cada endpoint, no la barra: `/hhi` no admite
 * ninguno (es todo el histórico observado), la cuota y la referencia se piden
 * por el segmento elegido, y `/bajas` es el único que entiende parte del
 * ámbito (`parametrosBajas`). Pasarle la barra entera a los demás sería
 * cachear por filtros que el endpoint ignora y enseñar como «filtrado» algo
 * que no lo está.
 */

import { useQuery } from "@tanstack/react-query";

import { apiGet } from "@/lib/api-client";
import { useFilterParams } from "@/lib/filters";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { competitiveKeys } from "@/lib/query-keys";

import { parametrosBajas, type BajasPor, type ConsultasDeSegmento, type SegmentoPor } from "./mercado-segmentos";

/** Lo que el backend cachea; pedirlo antes no trae nada nuevo. */
const FRESCO_MS = 5 * 60 * 1000;

/** Masa mínima de un segmento para tener HHI: el default de la API. */
export const MIN_CONTRATOS_HHI = 5;
/** Masa mínima de un grupo de bajas: el default de la API. */
export const MIN_CONTRATOS_BAJAS = 3;
/** Empresas que se enseñan del reparto de un segmento. */
export const EMPRESAS_CUOTA = 10;
/** Grupos de la tabla de bajas, los de más contratos. */
export const GRUPOS_BAJAS = 15;

export function useHhiSegmentos(por: SegmentoPor) {
  return useQuery({
    queryKey: competitiveKeys.hhi(por, MIN_CONTRATOS_HHI),
    queryFn: ({ signal }) =>
      apiGet("/api/v1/competitive/hhi", {
        params: { query: { segment_by: por, min_contratos: MIN_CONTRATOS_HHI } },
        signal,
      }),
    staleTime: FRESCO_MS,
    meta: META_ERROR_EN_LINEA,
  });
}

export function useCuotaSegmento(consulta: ConsultasDeSegmento["cuota"]) {
  const params: Record<string, string> = { ...consulta, limit: String(EMPRESAS_CUOTA) };
  return useQuery({
    queryKey: competitiveKeys.cuota(params),
    queryFn: ({ signal }) => apiGet("/api/v1/competitive/cuota", { params: { query: params }, signal }),
    enabled: consulta != null,
    staleTime: FRESCO_MS,
    meta: META_ERROR_EN_LINEA,
  });
}

export function useBajaReferencia(consulta: ConsultasDeSegmento["referencia"]) {
  const params: Record<string, string> = { ...consulta };
  return useQuery({
    queryKey: competitiveKeys.bajaReferencia(params),
    queryFn: ({ signal }) =>
      apiGet("/api/v1/competitive/bajas/referencia", { params: { query: params }, signal }),
    enabled: consulta != null,
    staleTime: FRESCO_MS,
    meta: META_ERROR_EN_LINEA,
  });
}

export function useBajasPorGrupo(por: BajasPor) {
  const filtros = useFilterParams();
  const params: Record<string, string> = {
    ...parametrosBajas(filtros),
    group_by: por,
    min_contratos: String(MIN_CONTRATOS_BAJAS),
    limit: String(GRUPOS_BAJAS),
  };
  return useQuery({
    queryKey: competitiveKeys.bajas(params),
    queryFn: ({ signal }) => apiGet("/api/v1/competitive/bajas", { params: { query: params }, signal }),
    staleTime: FRESCO_MS,
    meta: META_ERROR_EN_LINEA,
  });
}
