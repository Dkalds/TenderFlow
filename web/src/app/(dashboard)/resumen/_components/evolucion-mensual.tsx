"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { EmptyState } from "@/components/ui/empty-state";
import { CHART_SERIES } from "@/lib/chart-colors";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface EvolucionMensualProps {
  porMes: { mes: string; n_licitaciones: number; importe: number }[] | undefined;
  isLoading: boolean;
}

export function EvolucionMensual({ porMes, isLoading }: EvolucionMensualProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Evolucion Mensual</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[300px] w-full" />
        ) : porMes && porMes.length > 0 ? (
          <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={porMes}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="mes" tick={{ fontSize: 12 }} className="text-muted-foreground" />
                <YAxis tick={{ fontSize: 12 }} className="text-muted-foreground" />
                <Tooltip />
                <Area
                  type="monotone"
                  dataKey="n_licitaciones"
                  stroke={CHART_SERIES[0]}
                  fill={CHART_SERIES[0]}
                  fillOpacity={0.1}
                  name="Licitaciones"
                />
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
