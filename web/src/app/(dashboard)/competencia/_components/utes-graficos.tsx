"use client";

/**
 * Los cuatro gráficos de UTEs, en las dos parejas en que se leen: quién
 * participa y cómo evoluciona el fenómeno; y cómo se reparten esas
 * participaciones y quién mueve el importe.
 *
 * Todos pintan series que manda el backend tal cual (`top_miembros`,
 * `evolucion`) o el reparto en tramos de `utes-series.ts`; ninguno deriva un
 * total que el endpoint no haya dado.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { CHART_SERIES } from "@/lib/chart-colors";
import { formatCurrency, formatNumber, truncate } from "@/lib/utils";

import type {
  DistribucionBin,
  EvolucionEntry,
  TopMiembro,
} from "../_hooks/utes-types";

/** Participaciones por miembro y evolución temporal del fenómeno UTE. */
export function UtesGraficosMiembros({
  topMiembros,
  evolucion,
  isLoading,
}: {
  topMiembros: TopMiembro[] | undefined;
  evolucion: EvolucionEntry[] | undefined;
  isLoading: boolean;
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Top Miembros de UTEs</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : topMiembros && topMiembros.length > 0 ? (
            <ResponsiveContainer width="100%" height={Math.max(300, topMiembros.length * 32)}>
              <BarChart accessibilityLayer data={topMiembros} layout="vertical" margin={{ left: 180 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis type="number" tick={{ fontSize: 12 }} />
                <YAxis
                  dataKey="nombre"
                  type="category"
                  tick={{ fontSize: 11 }}
                  width={170}
                  tickFormatter={(v: string) => truncate(v, 30)}
                />
                <Tooltip formatter={(v) => formatNumber(v as number)} />
                <Bar dataKey="count" fill="hsl(280, 65%, 60%)" radius={[0, 4, 4, 0]} name="Participaciones" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Evolución Temporal de UTEs</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : evolucion && evolucion.length > 0 ? (
            <ResponsiveContainer width="100%" height={400}>
              <ComposedChart accessibilityLayer data={evolucion} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="periodo" tick={{ fontSize: 11 }} />
                <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v: number) => formatCurrency(v)}
                />
                <Tooltip
                  formatter={(v, name) =>
                    name === "Importe" ? formatCurrency(Number(v ?? 0)) : formatNumber(Number(v ?? 0))
                  }
                />
                <Legend />
                <Bar yAxisId="left" dataKey="count" fill="hsl(221, 83%, 53%)" radius={[4, 4, 0, 0]} name="Contratos" />
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="importe"
                  stroke="hsl(30, 80%, 55%)"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  name="Importe"
                />
              </ComposedChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/** Reparto de participaciones por tramo y los quince que más importe mueven. */
export function UtesGraficosDistribucion({
  memberDistribution,
  topMiembrosByImporte,
  isLoading,
}: {
  memberDistribution: DistribucionBin[];
  topMiembrosByImporte: TopMiembro[];
  isLoading: boolean;
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Distribución de Participaciones</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[300px] w-full" />
          ) : memberDistribution.length > 0 ? (
            <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart accessibilityLayer data={memberDistribution} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis dataKey="rango" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v) => [formatNumber(v as number), "Empresas"]} />
                  <Bar dataKey="miembros" fill={CHART_SERIES[0]} radius={[4, 4, 0, 0]} name="Empresas" />
                </BarChart>
              </ResponsiveContainer>
            </ChartErrorBoundary>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Top 15 Miembros por Importe</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : topMiembrosByImporte.length > 0 ? (
            <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={Math.max(300, topMiembrosByImporte.length * 28)}>
                <BarChart accessibilityLayer data={topMiembrosByImporte} layout="vertical" margin={{ left: 180 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis type="number" tick={{ fontSize: 12 }} tickFormatter={(v: number) => formatCurrency(v)} />
                  <YAxis
                    dataKey="nombre"
                    type="category"
                    tick={{ fontSize: 11 }}
                    width={170}
                    tickFormatter={(v: string) => truncate(v, 30)}
                  />
                  <Tooltip formatter={(v) => [formatCurrency(v as number), "Importe"]} />
                  <Bar dataKey="importe" fill={CHART_SERIES[1]} radius={[0, 4, 4, 0]} name="Importe" />
                </BarChart>
              </ResponsiveContainer>
            </ChartErrorBoundary>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
