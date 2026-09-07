"use client";

/**
 * Los cuatro gráficos de la serie mensual de Tendencias: volumen por mes,
 * importe acumulado, el waterfall de variación y el histograma de importes.
 *
 * El waterfall se carga bajo demanda (`ssr: false`): mide el ancho del
 * contenedor para repartir las barras, así que en servidor no tiene nada que
 * medir.
 */

import dynamic from "next/dynamic";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatNumber } from "@/lib/utils";
import type { TrendPoint } from "@/lib/api-types";

import type {
  CumulativePoint,
  HistogramBin,
  WaterfallPoint,
} from "../_hooks/use-tendencias-view";

const WaterfallChart = dynamic(() => import("@/components/charts/waterfall-chart").then(m => ({ default: m.WaterfallChart })), { ssr: false, loading: () => <Skeleton className="h-[420px] w-full rounded-md" /> });

export function TendenciasVolumen({
  series,
  isLoading,
}: {
  series: TrendPoint[];
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Licitaciones por Mes</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[350px] w-full" />
        ) : series.length > 0 ? (
          <ChartErrorBoundary>
          <ResponsiveContainer width="100%" height={350}>
            <BarChart accessibilityLayer data={series}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="period" tick={{ fontSize: 12 }} angle={-45} textAnchor="end" height={60} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value) => [formatNumber(value as number), "Licitaciones"]} />
              <Bar dataKey="count" fill="hsl(221, 83%, 53%)" radius={[4, 4, 0, 0]} name="Licitaciones" />
            </BarChart>
          </ResponsiveContainer>
            </ChartErrorBoundary>
        ) : (
          <EmptyState />
        )}
      </CardContent>
    </Card>
  );
}

export function TendenciasAcumulado({
  data,
  isLoading,
}: {
  data: CumulativePoint[];
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Importe Acumulado</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[350px] w-full" />
        ) : data.length > 0 ? (
          <ChartErrorBoundary>
          <ResponsiveContainer width="100%" height={350}>
            <AreaChart accessibilityLayer data={data}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="period" tick={{ fontSize: 12 }} angle={-45} textAnchor="end" height={60} />
              <YAxis tick={{ fontSize: 12 }} tickFormatter={(v: number) => formatCurrency(v)} />
              <Tooltip formatter={(value) => [formatCurrency(value as number), "Acumulado"]} />
              <Area type="monotone" dataKey="importe_acumulado" stroke="hsl(160, 60%, 45%)" fill="hsl(160, 60%, 45%)" fillOpacity={0.15} name="Importe Acumulado" />
            </AreaChart>
          </ResponsiveContainer>
            </ChartErrorBoundary>
        ) : (
          <EmptyState />
        )}
      </CardContent>
    </Card>
  );
}

export function TendenciasWaterfall({ data }: { data: WaterfallPoint[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Waterfall: Variacion Mensual</CardTitle>
      </CardHeader>
      <CardContent>
        <WaterfallChart data={data} height={320} />
      </CardContent>
    </Card>
  );
}

export function TendenciasHistograma({
  bins,
  /** Rango dinámico > 100×: sin escala log las colas se aplastan contra el eje. */
  useLogScale,
}: {
  bins: HistogramBin[];
  useLogScale: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Distribución de Importes</CardTitle>
      </CardHeader>
      <CardContent>
        <ChartErrorBoundary>
        <ResponsiveContainer width="100%" height={320}>
          <BarChart accessibilityLayer data={bins} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
            <YAxis dataKey="bin_label" type="category" tick={{ fontSize: 12 }} width={120} />
            <XAxis
              type="number"
              tick={{ fontSize: 12 }}
              scale={useLogScale ? "log" : "auto"}
              domain={useLogScale ? [1, "auto"] : [0, "auto"]}
              tickFormatter={(v: number) => formatNumber(v)}
            />
            <Tooltip formatter={(value) => [formatNumber(value as number), "Licitaciones"]} />
            <Bar dataKey="count" fill="hsl(280, 65%, 60%)" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
          </ChartErrorBoundary>
      </CardContent>
    </Card>
  );
}
