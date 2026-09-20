"use client";

/**
 * Datos y series de la vista Tendencias.
 *
 * Las dos peticiones (serie mensual con su cruce Mes×Estado, y la previsión de
 * volumen) y todas las derivaciones viven aquí. Ninguna inventa analítica: el
 * backend entrega la serie ya agregada sobre el dataset completo y aquí sólo se
 * suma, se acumula y se compara contra los doce meses anteriores (ADR-014).
 *
 * El heatmap Mes×Estado es el cruce REAL que `/analytics/trends` sirve en
 * `heatmap` (`GROUP BY mes, estado`). Hasta el RFC ux-tendencias #1 se fabricaba
 * aquí como producto de marginales del overview y se rotulaba «Estimado»; aquí
 * sólo se gira de lista de celdas a matriz.
 */

import { useMemo, useState } from "react";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import type { Schemas, TrendPoint } from "@/lib/api-types";

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
  /** Cruce real Mes×Estado: `row` = mes `YYYY-MM`, `col` = código de estado. */
  heatmap?: HeatmapCellDto[];
}

export type HeatmapCellDto = Schemas["HeatmapCell"];

/** Punto de la serie acumulada de importe. */
export interface CumulativePoint {
  period: string;
  importe_acumulado: number;
}

/** Matriz mes × estado del heatmap, con el máximo que fija la escala de color. */
export interface HeatmapMesEstado {
  estados: string[];
  meses: string[];
  /** `valores.get(\`${mes}|${estado}\`)`; ausente = 0 licitaciones. */
  valores: Map<string, number>;
  maxVal: number;
}

/**
 * Gira las celdas del backend a matriz. Los estados se ordenan por volumen
 * total (el más frecuente arriba) y los meses cronológicamente.
 */
export function heatmapFromCells(cells: HeatmapCellDto[] | undefined): HeatmapMesEstado | null {
  if (!cells || cells.length === 0) return null;
  const valores = new Map<string, number>();
  const porEstado = new Map<string, number>();
  const meses = new Set<string>();
  let maxVal = 0;
  for (const c of cells) {
    valores.set(`${c.row}|${c.col}`, c.value);
    porEstado.set(c.col, (porEstado.get(c.col) ?? 0) + c.value);
    meses.add(c.row);
    if (c.value > maxVal) maxVal = c.value;
  }
  const estados = Array.from(porEstado.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([e]) => e);
  return { estados, meses: Array.from(meses).sort(), valores, maxVal };
}

/**
 * Enlace al listado de las licitaciones publicadas en un mes `YYYY-MM` (y, si
 * se da, en un estado). Los parámetros del enlace sustituyen a los del ámbito
 * en `useScopedHref`: el mes de la barra es la razón de existir del enlace.
 */
export function mesHref(mes: string, estado?: string): string {
  const [y, m] = mes.split("-").map(Number);
  const ultimo = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const base = `/detalle?fecha_desde=${mes}-01&fecha_hasta=${mes}-${String(ultimo).padStart(2, "0")}`;
  return estado ? `${base}&estado=${encodeURIComponent(estado)}` : base;
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

  const { data: forecast, isLoading: forecastLoading } = useFilteredQuery<ForecastResponse>(
    ["analytics", "forecast", forecastMetric],
    `/api/v1/analytics/forecast/volume?months_ahead=6&metric=${forecastMetric}`,
    { staleTime: 5 * 60_000 },
  );

  const isLoading = trendsLoading;
  const error = trendsError;
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

  // Heatmap — cruce REAL (mes, estado) del backend, no un producto de marginales.
  const heatmapData = useMemo(() => heatmapFromCells(trends?.heatmap), [trends]);

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
