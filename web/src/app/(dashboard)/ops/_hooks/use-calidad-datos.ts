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
  /** Horas desde la última ingesta, o `null` si el backend no las mide. */
  hoursAgo: number | null;
  freshness: Frescura;
  chartData: ColumnCompleteness[];
  dlqCount: number;
  fechasNoIso: number;
}

export function useCalidadDatos(): CalidadDatos {
  const { data, isLoading, isError } = useQuery<QualityData>({
    queryKey: analyticsKeys.quality,
    queryFn: () => fetchWithAuth<QualityData>("/api/v1/analytics/quality"),
  });

  const hoursAgo = data?.last_scrape_hours_ago ?? null;

  return {
    data,
    isLoading,
    isError,
    hoursAgo,
    freshness: freshnessInfo(hoursAgo),
    chartData: completitudSeries(data),
    dlqCount: data?.dlq_count ?? 0,
    fechasNoIso: data?.fechas_no_iso ?? 0,
  };
}
