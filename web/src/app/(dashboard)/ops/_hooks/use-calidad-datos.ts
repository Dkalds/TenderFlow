"use client";

/**
 * Métricas de calidad del dataset: una sola llamada, y las derivaciones puras
 * que la pantalla consume ya resueltas.
 *
 * La cola de errores y la frescura de la ingesta salen de la misma respuesta
 * pero no se exponen aquí: las pinta la tira de salud (`health-strip.tsx`), que
 * comparte esta clave de caché.
 */

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { analyticsKeys } from "@/lib/query-keys";
import {
  completitudSeries,
  type ColumnCompleteness,
  type QualityData,
} from "../_components/calidad-datos/quality-data";

export interface CalidadDatos {
  data: QualityData | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => void;
  chartData: ColumnCompleteness[];
  fechasNoIso: number;
}

export function useCalidadDatos(): CalidadDatos {
  const { data, isLoading, isError, error, refetch } = useQuery<QualityData>({
    queryKey: analyticsKeys.quality,
    queryFn: () => fetchWithAuth<QualityData>("/api/v1/analytics/quality"),
    // El fallo se pinta en la pantalla (`PanelError`): sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  return {
    data,
    isLoading,
    isError,
    error,
    refetch: () => void refetch(),
    chartData: completitudSeries(data),
    fechasNoIso: data?.fechas_no_iso ?? 0,
  };
}
