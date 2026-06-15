"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { EmptyState } from "@/components/ui/empty-state";
import { formatNumber, formatCurrency, truncate } from "@/lib/utils";
import { CHART_SERIES } from "@/lib/chart-colors";
import { useFilters } from "@/lib/filters";
import { chartClickField, toggleValue } from "@/lib/chart-interaction";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface ActivityTechChartsProps {
  activityData: { mes: string; n_licitaciones: number; importe: number }[];
  techData: { tecnologia: string; count: number; importe: number; pct: number }[];
  isLoading: boolean;
  techLoading: boolean;
}

export function ActivityTechCharts({
  activityData,
  techData,
  isLoading,
  techLoading,
}: ActivityTechChartsProps) {
  const { tecnologias, setTecnologias } = useFilters();

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Actividad Mensual</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[300px] w-full" />
          ) : activityData.length > 0 ? (
            <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={activityData}>
                  <defs>
                    <linearGradient id="activity-bar" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={CHART_SERIES[0]} stopOpacity={0.95} />
                      <stop offset="100%" stopColor={CHART_SERIES[0]} stopOpacity={0.5} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis dataKey="mes" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip
                    formatter={(value, name) => {
                      if (name === "Importe") return [formatCurrency(value as number), name];
                      return [formatNumber(value as number), name];
                    }}
                  />
                  <Bar
                    dataKey="n_licitaciones"
                    fill="url(#activity-bar)"
                    radius={[4, 4, 0, 0]}
                    name="Licitaciones"
                  />
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
          <CardTitle className="text-base">Tecnologias en ultimo mes</CardTitle>
          <p className="text-xs text-muted-foreground">Clic en una tecnologia para filtrar</p>
        </CardHeader>
        <CardContent>
          {techLoading ? (
            <Skeleton className="h-[300px] w-full" />
          ) : techData.length > 0 ? (
            <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={Math.max(300, techData.length * 32)}>
                <BarChart data={techData} layout="vertical" margin={{ left: 100 }} className="cursor-pointer">
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis type="number" tick={{ fontSize: 12 }} />
                  <YAxis
                    dataKey="tecnologia"
                    type="category"
                    tick={{ fontSize: 12 }}
                    width={90}
                    tickFormatter={(v: string) => truncate(v, 18)}
                  />
                  <Tooltip
                    formatter={(value) => [formatNumber(value as number), "Licitaciones"]}
                  />
                  <Bar
                    dataKey="count"
                    fill={CHART_SERIES[1]}
                    radius={[0, 4, 4, 0]}
                    name="Licitaciones"
                    onClick={(entry) => {
                      const tec = chartClickField(entry, "tecnologia");
                      if (tec) setTecnologias(toggleValue(tec, tecnologias));
                    }}
                  />
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
