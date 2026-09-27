"use client";

/**
 * Métricas de calidad del dataset: una sola llamada, y las derivaciones puras
 * que la pantalla consume ya resueltas.
 *
 * `hoursAgo` se expone como `number | null` —y no como `number` con un cero por
 * defecto— porque «hace 0 horas» y «no se ha medido» son estados distintos y la
 * tarjeta de frescura los pinta distinto.
 */

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { analyticsKeys } from "@/lib/query-keys";
import {
  completitudSeries,
  freshnessInfo,
  type ColumnCompleteness,
  type Frescura,
  type QualityData,
} from "../_components/calidad-datos/quality-data";

export interface CalidadDatos {
  data: QualityData | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => void;
  /** Horas desde la última ingesta, o `null` si el backend no las mide. */
  hoursAgo: number | null;
  freshness: Frescura;
  chartData: ColumnCompleteness[];
  dlqCount: number;
  fechasNoIso: number;
}

export function useCalidadDatos(): CalidadDatos {
  const { data, isLoading, isError, error, refetch } = useQuery<QualityData>({
    queryKey: analyticsKeys.quality,
    queryFn: () => fetchWithAuth<QualityData>("/api/v1/analytics/quality"),
    // El fallo se pinta en la pantalla (`PanelError`): sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  const hoursAgo = data?.last_scrape_hours_ago ?? null;

  return {
    data,
    isLoading,
    isError,
    error,
    refetch: () => void refetch(),
    hoursAgo,
    freshness: freshnessInfo(hoursAgo),
    chartData: completitudSeries(data),
    dlqCount: data?.dlq_count ?? 0,
    fechasNoIso: data?.fechas_no_iso ?? 0,
  };
}
