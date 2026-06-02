"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { EmptyState } from "@/components/ui/empty-state";
import { truncate } from "@/lib/utils";
import { CHART_SERIES } from "@/lib/chart-colors";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface TopOrganosChartProps {
  topOrganos: { organo_contratacion: string; n: number; importe: number }[] | undefined;
  isLoading: boolean;
}

export function TopOrganosChart({ topOrganos, isLoading }: TopOrganosChartProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Top Organos Contratantes</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : topOrganos && topOrganos.length > 0 ? (
          <ChartErrorBoundary>
            <ResponsiveContainer
              width="100%"
              height={Math.max(300, topOrganos.length * 40)}
            >
              <BarChart
                data={topOrganos.slice(0, 15)}
                layout="vertical"
                margin={{ left: 200 }}
              >
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis type="number" tick={{ fontSize: 12 }} />
                <YAxis
                  dataKey="organo_contratacion"
                  type="category"
                  tick={{ fontSize: 12 }}
                  width={190}
                  tickFormatter={(v: string) => truncate(v, 35)}
                />
                <Tooltip />
                <Bar
                  dataKey="n"
                  fill={CHART_SERIES[0]}
                  radius={[0, 4, 4, 0]}
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
  );
}
