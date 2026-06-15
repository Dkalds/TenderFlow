"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { EmptyState } from "@/components/ui/empty-state";
import { formatNumber, truncate } from "@/lib/utils";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";
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
  PieChart,
  Pie,
  Cell,
} from "recharts";

interface EstadoTiposChartsProps {
  porEstado: { estado: string; n: number }[] | undefined;
  tiposProyectoData: { tipo: string; count: number; importe: number }[];
  isLoading: boolean;
  tiposLoading: boolean;
}

export function EstadoTiposCharts({
  porEstado,
  tiposProyectoData,
  isLoading,
  tiposLoading,
}: EstadoTiposChartsProps) {
  const { estados, setEstados } = useFilters();

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Distribucion por Estado</CardTitle>
          <p className="text-xs text-muted-foreground">Clic en un estado para filtrar</p>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[320px] w-full" />
          ) : porEstado && porEstado.length > 0 ? (
            <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={320}>
                <PieChart className="cursor-pointer">
                  <Pie
                    data={porEstado}
                    dataKey="n"
                    nameKey="estado"
                    cx="50%"
                    cy="50%"
                    outerRadius={110}
                    innerRadius={55}
                    onClick={(entry) => {
                      const estado = chartClickField(entry, "estado");
                      if (estado) setEstados(toggleValue(estado, estados));
                    }}
                    label={({ name, value }: { name?: string; value?: number }) =>
                      `${name ?? ""}: ${value ?? 0}`
                    }
                  >
                    {porEstado.map((_, idx) => (
                      <Cell key={idx} fill={getSeriesColor(idx)} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </ChartErrorBoundary>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Tipos de Proyecto</CardTitle>
        </CardHeader>
        <CardContent>
          {tiposLoading ? (
            <Skeleton className="h-[320px] w-full" />
          ) : tiposProyectoData.length > 0 ? (
            <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={Math.max(300, tiposProyectoData.length * 36)}>
                <BarChart data={tiposProyectoData} layout="vertical" margin={{ left: 120 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis type="number" tick={{ fontSize: 12 }} />
                  <YAxis
                    dataKey="tipo"
                    type="category"
                    tick={{ fontSize: 12 }}
                    width={110}
                    tickFormatter={(v: string) => truncate(v, 20)}
                  />
                  <Tooltip
                    formatter={(value) => [formatNumber(value as number), "Licitaciones"]}
                  />
                  <Bar dataKey="count" fill={CHART_SERIES[0]} radius={[0, 4, 4, 0]} name="Licitaciones" />
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
