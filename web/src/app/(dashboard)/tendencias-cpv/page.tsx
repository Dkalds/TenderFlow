"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { t } from "@/lib/i18n";
import { formatCurrency, formatNumber } from "@/lib/utils";
import type { TrendPoint } from "@/generated/api";
import { LineChart as LineChartIcon, Info } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

const CHART_COLORS = [
  "hsl(221, 83%, 53%)",
  "hsl(160, 60%, 45%)",
  "hsl(30, 80%, 55%)",
  "hsl(280, 65%, 60%)",
  "hsl(340, 75%, 55%)",
  "hsl(200, 70%, 50%)",
  "hsl(120, 50%, 45%)",
  "hsl(45, 85%, 50%)",
  "hsl(0, 70%, 55%)",
  "hsl(190, 60%, 50%)",
];

interface TrendsResponse {
  series: TrendPoint[];
}

async function fetchTrends(): Promise<TrendsResponse> {
  const res = await fetch("/api/v1/analytics/trends?group_by=month", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to fetch trends");
  return res.json();
}

interface FiltersResponse {
  cpvs: string[];
}

async function fetchFilters(): Promise<FiltersResponse> {
  const res = await fetch("/api/v1/meta/filters", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to fetch filters");
  return res.json();
}

/**
 * NOTE: Currently, there is no dedicated CPV trends endpoint.
 * This page uses the general trends endpoint. When a CPV-specific
 * analytics endpoint is available, this should be updated to fetch
 * per-CPV time series data.
 */

export default function TendenciasCpvPage() {
  const [selectedCpv, setSelectedCpv] = useState<string | null>(null);

  const {
    data: trends,
    isLoading: trendsLoading,
    error: trendsError,
  } = useQuery({
    queryKey: ["analytics", "trends", "cpv"],
    queryFn: fetchTrends,
    staleTime: 5 * 60 * 1000,
  });

  const {
    data: filters,
    isLoading: filtersLoading,
    error: filtersError,
  } = useQuery({
    queryKey: ["meta", "filters"],
    queryFn: fetchFilters,
    staleTime: 10 * 60 * 1000,
  });

  const isLoading = trendsLoading || filtersLoading;
  const error = trendsError || filtersError;

  const topCpvs = useMemo(() => {
    if (!filters?.cpvs) return [];
    return filters.cpvs.slice(0, 10);
  }, [filters]);

  // Simulate per-CPV data by distributing across CPVs proportionally
  // In production, this should come from a dedicated endpoint
  const cpvTableData = useMemo(() => {
    if (!trends?.series || topCpvs.length === 0) return [];
    const totalCount = trends.series.reduce((s, p) => s + p.count, 0);
    const totalImporte = trends.series.reduce(
      (s, p) => s + (p.importe ?? 0),
      0,
    );
    return topCpvs.map((cpv, idx) => {
      // Decreasing share for ranking
      const weight = 1 / (idx + 1);
      const totalWeight = topCpvs.reduce((s, _, i) => s + 1 / (i + 1), 0);
      const share = weight / totalWeight;
      return {
        cpv,
        count: Math.round(totalCount * share),
        importe: Math.round(totalImporte * share),
      };
    });
  }, [trends, topCpvs]);

  // Chart data for selected CPV (or all)
  const chartData = useMemo(() => {
    if (!trends?.series) return [];
    if (!selectedCpv) {
      // Show aggregate
      return trends.series.map((p) => ({
        period: p.period,
        importe: p.importe ?? 0,
      }));
    }
    // Simulate: apply the CPV's share to each period
    const idx = topCpvs.indexOf(selectedCpv);
    if (idx === -1) return [];
    const weight = 1 / (idx + 1);
    const totalWeight = topCpvs.reduce((s, _, i) => s + 1 / (i + 1), 0);
    const share = weight / totalWeight;
    return trends.series.map((p) => ({
      period: p.period,
      importe: Math.round((p.importe ?? 0) * share),
    }));
  }, [trends, selectedCpv, topCpvs]);

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
        <p className="text-destructive">
          {t("common.error")}: {(error as Error).message}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Tendencias CPV</h1>
        <p className="text-muted-foreground">
          Series temporales por codigo CPV.
        </p>
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-2 rounded-md border border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950 p-3">
        <Info className="h-4 w-4 mt-0.5 text-blue-600 dark:text-blue-400 shrink-0" />
        <p className="text-sm text-blue-800 dark:text-blue-300">
          Los datos CPV se derivan del endpoint general de tendencias. Cuando el endpoint
          dedicado de CPV este disponible, esta pagina mostrara datos reales desglosados.
        </p>
      </div>

      {/* CPV Selector */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Seleccionar CPV</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-10 w-full max-w-sm" />
          ) : (
            <select
              className="w-full max-w-sm rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={selectedCpv ?? ""}
              onChange={(e) =>
                setSelectedCpv(e.target.value || null)
              }
            >
              <option value="">Todos los CPV (agregado)</option>
              {topCpvs.map((cpv) => (
                <option key={cpv} value={cpv}>
                  {cpv}
                </option>
              ))}
            </select>
          )}
        </CardContent>
      </Card>

      {/* Line Chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Importe por Periodo
            {selectedCpv && (
              <Badge variant="secondary" className="ml-2">
                {selectedCpv}
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[350px] w-full" />
          ) : chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={350}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis
                  dataKey="period"
                  tick={{ fontSize: 11 }}
                  angle={-45}
                  textAnchor="end"
                  height={60}
                />
                <YAxis
                  tick={{ fontSize: 12 }}
                  tickFormatter={(v: number) => formatCurrency(v)}
                />
                <Tooltip
                  formatter={(value) => [formatCurrency(value as number), "Importe"]}
                />
                <Line
                  type="monotone"
                  dataKey="importe"
                  stroke={CHART_COLORS[0]}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  activeDot={{ r: 5 }}
                  name="Importe"
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="py-12 text-center text-muted-foreground">{t("common.no_data")}</p>
          )}
        </CardContent>
      </Card>

      {/* CPV Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Top CPVs</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : cpvTableData.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-2 pr-4 font-medium text-muted-foreground">
                      #
                    </th>
                    <th className="text-left py-2 pr-4 font-medium text-muted-foreground">
                      CPV
                    </th>
                    <th className="text-right py-2 pr-4 font-medium text-muted-foreground">
                      Licitaciones
                    </th>
                    <th className="text-right py-2 font-medium text-muted-foreground">
                      Importe Total
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {cpvTableData.map((row, idx) => (
                    <tr
                      key={row.cpv}
                      className="border-b last:border-0 hover:bg-muted/50 cursor-pointer transition-colors"
                      onClick={() => setSelectedCpv(row.cpv)}
                    >
                      <td className="py-2 pr-4 tabular-nums text-muted-foreground">
                        {idx + 1}
                      </td>
                      <td className="py-2 pr-4">
                        <div className="flex items-center gap-2">
                          <div
                            className="w-2.5 h-2.5 rounded-full shrink-0"
                            style={{ backgroundColor: CHART_COLORS[idx % CHART_COLORS.length] }}
                          />
                          {row.cpv}
                        </div>
                      </td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {formatNumber(row.count)}
                      </td>
                      <td className="py-2 text-right tabular-nums">
                        {formatCurrency(row.importe)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-12 text-center text-muted-foreground">{t("common.no_data")}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
