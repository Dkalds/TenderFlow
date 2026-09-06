"use client";

/**
 * Los tres gráficos de Tendencias CPV: el multilínea de importe por periodo
 * (con el botón que abre la previsión), la previsión global superpuesta y el
 * ranking Top 15 por importe.
 */

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { BarChart3 } from "lucide-react";

import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";
import { formatCurrency } from "@/lib/utils";

import type { ForecastRow } from "../_hooks/forecast-series";
import type {
  CpvChartRow,
  CpvSeries,
  TopCpv,
} from "../_hooks/use-tendencias-cpv-view";

export function TendenciasCpvSeries({
  allCpvs,
  effectiveCpvs,
  data,
  showForecast,
  onToggleForecast,
  isLoading,
}: {
  allCpvs: CpvSeries[];
  effectiveCpvs: Set<string>;
  data: CpvChartRow[];
  showForecast: boolean;
  onToggleForecast: () => void;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">
          Importe por Periodo
          {effectiveCpvs.size > 0 && (
            <Badge variant="secondary" className="ml-2 text-xs">{effectiveCpvs.size} CPVs</Badge>
          )}
        </CardTitle>
        <Button
          variant={showForecast ? "default" : "outline"}
          size="sm"
          onClick={onToggleForecast}
        >
          <BarChart3 className="h-4 w-4 mr-1" />
          Previsión
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[350px] w-full" />
        ) : data.length > 0 ? (
          <ChartErrorBoundary>
          <ResponsiveContainer width="100%" height={350}>
            <LineChart accessibilityLayer data={data}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="period" tick={{ fontSize: 12 }} angle={-45} textAnchor="end" height={60} />
              <YAxis tick={{ fontSize: 12 }} tickFormatter={(v: number) => formatCurrency(v)} />
              <Tooltip formatter={(value) => [formatCurrency(value as number), ""]} />
              {allCpvs
                .filter((c) => effectiveCpvs.has(c.cpv))
                .map((c) => (
                  <Line
                    key={c.cpv}
                    type="monotone"
                    dataKey={c.cpv}
                    stroke={getSeriesColor(allCpvs.indexOf(c))}
                    strokeWidth={2}
                    dot={{ r: 2 }}
                    activeDot={{ r: 4 }}
                    name={c.label || c.cpv}
                  />
                ))}
            </LineChart>
          </ResponsiveContainer>
            </ChartErrorBoundary>
        ) : (
          <EmptyState />
        )}
      </CardContent>
    </Card>
  );
}

export function TendenciasCpvForecast({
  data,
  isLoading,
}: {
  data: ForecastRow[];
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle className="text-base">Previsión Volumen (6 meses)</CardTitle>
          <Badge variant="outline" className="text-amber-600 border-amber-400">
            Global del mercado
          </Badge>
        </div>
        <CardDescription>
          Previsión del volumen <strong>global</strong>, no de los CPV
          seleccionados arriba. Pendiente de soportar forecast por CPV en el
          backend.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[300px] w-full" />
        ) : data.length > 0 ? (
          <ChartErrorBoundary>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart accessibilityLayer data={data}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="mes" tick={{ fontSize: 12 }} angle={-45} textAnchor="end" height={60} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Area type="monotone" dataKey="upper" stroke="none" fill={CHART_SERIES[0]} fillOpacity={0.1} />
              {/* Goma theme-safe: token de fondo de la card, no blanco (rompía en dark mode). */}
              <Area type="monotone" dataKey="lower" stroke="none" fill="hsl(var(--card))" fillOpacity={1} />
              <Line type="monotone" dataKey="historico" stroke={CHART_SERIES[0]} strokeWidth={2} dot={{ r: 2 }} />
              <Line type="monotone" dataKey="forecast_val" stroke={CHART_SERIES[0]} strokeWidth={2} strokeDasharray="6 3" dot={{ r: 2 }} />
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

export function TendenciasCpvTop({
  topCpvs,
  isLoading,
}: {
  topCpvs: TopCpv[];
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Top 15 CPV por Importe</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[400px] w-full" />
        ) : topCpvs.length > 0 ? (
          <ChartErrorBoundary>
          <ResponsiveContainer width="100%" height={Math.max(300, topCpvs.length * 30)}>
            <BarChart accessibilityLayer data={topCpvs} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <YAxis dataKey="cpv" type="category" tick={{ fontSize: 12 }} width={140} />
              <XAxis type="number" tick={{ fontSize: 12 }} tickFormatter={(v: number) => formatCurrency(v)} />
              <Tooltip formatter={(value) => [formatCurrency(value as number), "Importe"]} />
              <Bar dataKey="importe_total" fill={CHART_SERIES[0]} radius={[0, 4, 4, 0]} name="Importe" />
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
