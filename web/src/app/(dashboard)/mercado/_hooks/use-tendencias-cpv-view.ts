"use client";

/**
 * Estado y series de la vista Tendencias CPV.
 *
 * La selección de CPVs tiene dos capas a propósito: `selectedCpvs` es lo que ha
 * tocado el usuario y `effectiveCpvs` lo que se pinta. Mientras nadie toca
 * nada, la segunda cae en los tres CPVs con más peso — sin ese arranque el
 * gráfico se abriría vacío y parecería roto.
 *
 * Las series llegan ya agregadas por periodo desde el backend; aquí sólo se
 * giran de «una serie por CPV» a «una fila por periodo», que es la forma que
 * come el `LineChart` (ADR-014: no se deriva ningún total nuevo).
 */

import { useMemo, useState } from "react";

import { useFilteredQuery } from "@/hooks/use-filtered-query";

import {
  splitForecastSeries,
  type ForecastResponse,
  type ForecastRow,
} from "./forecast-series";

export interface CpvSeriesPoint {
  period: string;
  count: number;
  importe: number;
}

export interface CpvSeries {
  cpv: string;
  label: string;
  series: CpvSeriesPoint[];
}

export interface TopCpv {
  cpv: string;
  importe_total: number;
  count: number;
}

export interface TrendsCpvResponse {
  series_by_cpv: CpvSeries[];
  top_cpv_by_importe: TopCpv[];
  summary: Record<string, unknown>;
}

/**
 * Fila del gráfico multilínea: la clave `period` más una clave por CPV
 * seleccionado (el código CPV es el `dataKey` de su línea).
 */
export type CpvChartRow = Record<string, number | string>;

/** Fila de la tabla Top CPVs, con el puesto ya resuelto. */
export interface CpvTableRow {
  rank: number;
  cpv: string;
  count: number;
  importe: number;
}

export function useTendenciasCpvView() {
  const [selectedCpvs, setSelectedCpvs] = useState<Set<string>>(new Set());
  const [showForecast, setShowForecast] = useState(false);

  const { data: cpvData, isLoading, error } = useFilteredQuery<TrendsCpvResponse>(
    ["analytics", "trends-cpv"],
    "/api/v1/analytics/trends-cpv",
    { staleTime: 5 * 60_000 },
  );

  const { data: forecast, isLoading: forecastLoading } = useFilteredQuery<ForecastResponse>(
    ["analytics", "forecast", "volume"],
    "/api/v1/analytics/forecast/volume?months_ahead=6",
    { staleTime: 5 * 60_000, enabled: showForecast },
  );

  const allCpvs = useMemo(() => cpvData?.series_by_cpv ?? [], [cpvData]);
  const topCpvs = useMemo(() => cpvData?.top_cpv_by_importe?.slice(0, 15) ?? [], [cpvData]);

  // Initialize selection to first 3 CPVs
  const effectiveCpvs = useMemo(() => {
    if (selectedCpvs.size > 0) return selectedCpvs;
    return new Set(allCpvs.slice(0, 3).map((c) => c.cpv));
  }, [selectedCpvs, allCpvs]);

  const toggleCpv = (cpv: string) => {
    setSelectedCpvs((prev) => {
      const next = new Set(prev.size > 0 ? prev : effectiveCpvs);
      if (next.has(cpv)) next.delete(cpv);
      else next.add(cpv);
      return next;
    });
  };

  // Build merged chart data: period -> { period, cpv1, cpv2, ... }
  const chartData = useMemo<CpvChartRow[]>(() => {
    const selected = allCpvs.filter((c) => effectiveCpvs.has(c.cpv));
    if (selected.length === 0) return [];

    const periodMap = new Map<string, Record<string, number>>();
    for (const cpvSeries of selected) {
      for (const pt of cpvSeries.series) {
        if (!periodMap.has(pt.period)) periodMap.set(pt.period, {});
        periodMap.get(pt.period)![cpvSeries.cpv] = pt.importe;
      }
    }

    return Array.from(periodMap.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([period, vals]): CpvChartRow => ({ period, ...vals }));
  }, [allCpvs, effectiveCpvs]);

  const forecastData = useMemo<ForecastRow[]>(
    () => splitForecastSeries(forecast?.series),
    [forecast],
  );

  // CPV table data from real endpoint
  const cpvTableData = useMemo<CpvTableRow[]>(() => {
    return topCpvs.map((item, idx) => ({
      rank: idx + 1,
      cpv: item.cpv,
      count: item.count,
      importe: item.importe_total,
    }));
  }, [topCpvs]);

  return {
    allCpvs,
    topCpvs,
    effectiveCpvs,
    toggleCpv,
    chartData,
    forecastData,
    forecastLoading,
    showForecast,
    setShowForecast,
    cpvTableData,
    isLoading,
    error,
  };
}
