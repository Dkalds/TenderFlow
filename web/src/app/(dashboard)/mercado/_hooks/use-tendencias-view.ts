"use client";

/**
 * Datos y series de la vista Tendencias.
 *
 * Las tres peticiones (serie mensual, overview por estado/mes y la previsión de
 * volumen) y todas las derivaciones viven aquí. Ninguna inventa analítica: el
 * backend entrega la serie ya agregada sobre el dataset completo y aquí sólo se
 * suma, se acumula y se compara contra los doce meses anteriores (ADR-014).
 *
 * La única excepción es `heatmapData`, que es un ESTIMADO declarado: producto de
 * marginales, no un cruce real. La vista lo rotula como tal.
 */

import { useMemo, useState } from "react";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import type { TrendPoint } from "@/lib/api-types";

import {
  splitForecastSeries,
  type ForecastResponse,
  type ForecastRow,
} from "./forecast-series";

export interface WaterfallPoint {
  period: string;
  delta: number;
  cumulative: number;
}

export interface HistogramBin {
  bin_label: string;
  count: number;
}

export interface MesPico {
  mes: string;
  importe: number;
  count: number;
}

export interface TrendsResponse {
  series: TrendPoint[];
  waterfall: WaterfallPoint[];
  histogram_bins: HistogramBin[];
  mes_pico: MesPico;
}

export interface OverviewResponse {
  por_estado: { estado: string; n: number }[];
  por_mes: { mes: string; n_licitaciones: number; importe: number }[];
}

/** Punto de la serie acumulada de importe. */
export interface CumulativePoint {
  period: string;
  importe_acumulado: number;
}

/** Matriz mes × estado del heatmap, con el máximo que fija la escala de color. */
export interface HeatmapEstimado {
  estados: string[];
  meses: string[];
  grid: { mes: string; estado: string; value: number }[];
  maxVal: number;
}

export type ForecastMetric = "count" | "sum";

/**
 * Variación interanual: los últimos doce meses contra la ventana anterior.
 *
 * OJO con el denominador (ADR-014): la ventana previa es `slice(-24, -12)`, que
 * sólo tiene doce meses cuando la serie llega a veinticuatro. Entre trece y
 * veintitrés puntos devuelve igualmente un número, comparando doce meses contra
 * una ventana MÁS CORTA — el porcentaje sale inflado. Es el comportamiento que
 * hay en producción desde siempre y se conserva tal cual aquí; el arreglo
 * (exigir 24 puntos, o normalizar por el tamaño de cada ventana) cambia la cifra
 * en pantalla, así que va aparte. Los tests lo dejan clavado.
 */
export function computeYoY(series: TrendPoint[], field: "count" | "importe"): number | null {
  if (series.length < 13) return null;
  const recent = series.slice(-12);
  const prior = series.slice(-24, -12);
  if (prior.length === 0) return null;
  const sumRecent = recent.reduce((s, p) => s + (field === "count" ? p.count : (p.importe ?? 0)), 0);
  const sumPrior = prior.reduce((s, p) => s + (field === "count" ? p.count : (p.importe ?? 0)), 0);
  if (sumPrior === 0) return null;
  return ((sumRecent - sumPrior) / sumPrior) * 100;
}

export function useTendenciasView() {
  const [forecastMetric, setForecastMetric] = useState<ForecastMetric>("count");

  const { data: trends, isLoading: trendsLoading, error: trendsError } = useFilteredQuery<TrendsResponse>(
    ["analytics", "trends"],
    "/api/v1/analytics/trends?group_by=month",
    { staleTime: 5 * 60_000 },
  );

  const { data: overview, isLoading: overviewLoading, error: overviewError } = useFilteredQuery<OverviewResponse>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    { staleTime: 5 * 60_000 },
  );

  const { data: forecast, isLoading: forecastLoading } = useFilteredQuery<ForecastResponse>(
    ["analytics", "forecast", forecastMetric],
    `/api/v1/analytics/forecast/volume?months_ahead=6&metric=${forecastMetric}`,
    { staleTime: 5 * 60_000 },
  );

  const isLoading = trendsLoading || overviewLoading;
  const error = trendsError || overviewError;
  const series = useMemo(() => trends?.series ?? [], [trends]);

  const totalCount = useMemo(() => series.reduce((s, p) => s + p.count, 0), [series]);
  const totalImporte = useMemo(() => series.reduce((s, p) => s + (p.importe ?? 0), 0), [series]);
  const yoyCount = useMemo(() => computeYoY(series, "count"), [series]);
  const yoyImporte = useMemo(() => computeYoY(series, "importe"), [series]);

  const cumulativeData = useMemo<CumulativePoint[]>(() => {
    const result: CumulativePoint[] = [];
    let acc = 0;
    for (const p of series) {
      acc += p.importe ?? 0;
      result.push({ period: p.period, importe_acumulado: acc });
    }
    return result;
  }, [series]);

  // Heatmap — ESTIMADO (no es un cruce real): producto de marginales
  // (distribución global de estados × volumen mensual). El cruce real (mes,estado)
  // debe venir de un cross-tab en backend (ver RFC ux-tendencias). Etiquetado en UI
  // como "Estimado" mientras tanto, para no presentar síntesis como dato real.
  const heatmapData = useMemo<HeatmapEstimado | null>(() => {
    if (!overview) return null;
    const estados = overview.por_estado.map((e) => e.estado);
    const meses = overview.por_mes.map((m) => m.mes);
    const totalByEstado = overview.por_estado.reduce((s, e) => s + e.n, 0);
    const grid: { mes: string; estado: string; value: number }[] = [];
    let maxVal = 0;
    for (const m of overview.por_mes) {
      for (const e of overview.por_estado) {
        const proportion = totalByEstado > 0 ? e.n / totalByEstado : 0;
        const value = Math.round(m.n_licitaciones * proportion);
        if (value > maxVal) maxVal = value;
        grid.push({ mes: m.mes, estado: e.estado, value });
      }
    }
    return { estados, meses, grid, maxVal };
  }, [overview]);

  // Histogram: detect if log scale needed
  const histBins = trends?.histogram_bins ?? [];
  const histMax = Math.max(...histBins.map((b) => b.count), 1);
  const histMin = Math.min(...histBins.filter((b) => b.count > 0).map((b) => b.count), histMax);
  const useLogScale = histMax / histMin > 100;

  const forecastData = useMemo<ForecastRow[]>(
    () => splitForecastSeries(forecast?.series),
    [forecast],
  );

  return {
    series,
    mesPico: trends?.mes_pico,
    waterfall: trends?.waterfall ?? [],
    histBins,
    useLogScale,
    cumulativeData,
    heatmapData,
    totalCount,
    totalImporte,
    yoyCount,
    yoyImporte,
    forecast,
    forecastData,
    forecastLoading,
    forecastMetric,
    setForecastMetric,
    isLoading,
    error,
  };
}
