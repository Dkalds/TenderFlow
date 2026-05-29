"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { t } from "@/lib/i18n";
import { formatCurrency, formatNumber, formatPercent, cn } from "@/lib/utils";
import type { TrendPoint } from "@/generated/api";
import { Hash, DollarSign, TrendingUp, TrendingDown } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
} from "recharts";

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

/** Compute YoY change given monthly series. Compares last 12 months vs prior 12. */
function computeYoY(series: TrendPoint[], field: "count" | "importe") {
  if (series.length < 13) return null;
  const recent = series.slice(-12);
  const prior = series.slice(-24, -12);
  if (prior.length === 0) return null;
  const sumRecent = recent.reduce(
    (s, p) => s + (field === "count" ? p.count : (p.importe ?? 0)),
    0,
  );
  const sumPrior = prior.reduce(
    (s, p) => s + (field === "count" ? p.count : (p.importe ?? 0)),
    0,
  );
  if (sumPrior === 0) return null;
  return ((sumRecent - sumPrior) / sumPrior) * 100;
}

// Build a list of unique estados found across series for the heatmap.
// Since the trends endpoint returns aggregated points without estado breakdown,
// we simulate it using the overview endpoint's por_estado data.
// For the heatmap we fetch a second endpoint.
interface OverviewResponse {
  por_estado: { estado: string; n: number }[];
  por_mes: { mes: string; n_licitaciones: number; importe: number }[];
}

async function fetchOverview(): Promise<OverviewResponse> {
  const res = await fetch("/api/v1/analytics/overview", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to fetch overview");
  return res.json();
}

const HEATMAP_COLORS = [
  "bg-gray-100 dark:bg-gray-800",
  "bg-blue-100 dark:bg-blue-900",
  "bg-blue-200 dark:bg-blue-800",
  "bg-blue-300 dark:bg-blue-700",
  "bg-blue-400 dark:bg-blue-600",
  "bg-blue-500 dark:bg-blue-500",
  "bg-blue-600 dark:bg-blue-400",
];

function getHeatmapColor(value: number, max: number): string {
  if (max === 0 || value === 0) return HEATMAP_COLORS[0];
  const idx = Math.min(
    Math.floor((value / max) * (HEATMAP_COLORS.length - 1)) + 1,
    HEATMAP_COLORS.length - 1,
  );
  return HEATMAP_COLORS[idx];
}

export default function TendenciasPage() {
  const {
    data: trends,
    isLoading: trendsLoading,
    error: trendsError,
  } = useQuery({
    queryKey: ["analytics", "trends"],
    queryFn: fetchTrends,
    staleTime: 5 * 60 * 1000,
  });

  const {
    data: overview,
    isLoading: overviewLoading,
    error: overviewError,
  } = useQuery({
    queryKey: ["analytics", "overview"],
    queryFn: fetchOverview,
    staleTime: 5 * 60 * 1000,
  });

  const isLoading = trendsLoading || overviewLoading;
  const error = trendsError || overviewError;

  const series = trends?.series ?? [];

  const totalCount = useMemo(
    () => series.reduce((s, p) => s + p.count, 0),
    [series],
  );
  const totalImporte = useMemo(
    () => series.reduce((s, p) => s + (p.importe ?? 0), 0),
    [series],
  );
  const yoyCount = useMemo(() => computeYoY(series, "count"), [series]);
  const yoyImporte = useMemo(() => computeYoY(series, "importe"), [series]);

  // Cumulative importe data
  const cumulativeData = useMemo(() => {
    let acc = 0;
    return series.map((p) => {
      acc += p.importe ?? 0;
      return { period: p.period, importe_acumulado: acc };
    });
  }, [series]);

  // Heatmap: month x estado grid from overview data
  const heatmapData = useMemo(() => {
    if (!overview) return null;
    const estados = overview.por_estado.map((e) => e.estado);
    const meses = overview.por_mes.map((m) => m.mes);
    // Synthesize: distribute each month's count across estados proportionally
    const totalByEstado = overview.por_estado.reduce(
      (s, e) => s + e.n,
      0,
    );
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
        <h1 className="text-2xl font-bold tracking-tight">Tendencias</h1>
        <p className="text-muted-foreground">
          Evolucion de publicaciones y montos a lo largo del tiempo.
        </p>
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Total Licitaciones"
          value={isLoading ? undefined : formatNumber(totalCount)}
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title="Importe Total"
          value={isLoading ? undefined : formatCurrency(totalImporte)}
          icon={DollarSign}
          loading={isLoading}
        />
        <KpiCard
          title="Var. YoY (cantidad)"
          value={isLoading ? undefined : yoyCount != null ? formatPercent(yoyCount) : "-"}
          icon={yoyCount != null && yoyCount >= 0 ? TrendingUp : TrendingDown}
          trend={yoyCount ?? undefined}
          loading={isLoading}
        />
        <KpiCard
          title="Var. YoY (importe)"
          value={isLoading ? undefined : yoyImporte != null ? formatPercent(yoyImporte) : "-"}
          icon={yoyImporte != null && yoyImporte >= 0 ? TrendingUp : TrendingDown}
          trend={yoyImporte ?? undefined}
          loading={isLoading}
        />
      </div>

      {/* Bar Chart: Licitaciones per month */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Licitaciones por Mes</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[350px] w-full" />
          ) : series.length > 0 ? (
            <ResponsiveContainer width="100%" height={350}>
              <BarChart data={series}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="period" tick={{ fontSize: 11 }} angle={-45} textAnchor="end" height={60} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip
                  formatter={(value) => [formatNumber(value as number), "Licitaciones"]}
                />
                <Bar
                  dataKey="count"
                  fill="hsl(221, 83%, 53%)"
                  radius={[4, 4, 0, 0]}
                  name="Licitaciones"
                />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="py-12 text-center text-muted-foreground">{t("common.no_data")}</p>
          )}
        </CardContent>
      </Card>

      {/* Area Chart: Importe acumulado */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Importe Acumulado</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[350px] w-full" />
          ) : cumulativeData.length > 0 ? (
            <ResponsiveContainer width="100%" height={350}>
              <AreaChart data={cumulativeData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="period" tick={{ fontSize: 11 }} angle={-45} textAnchor="end" height={60} />
                <YAxis
                  tick={{ fontSize: 12 }}
                  tickFormatter={(v: number) => formatCurrency(v)}
                />
                <Tooltip
                  formatter={(value) => [formatCurrency(value as number), "Acumulado"]}
                />
                <Area
                  type="monotone"
                  dataKey="importe_acumulado"
                  stroke="hsl(160, 60%, 45%)"
                  fill="hsl(160, 60%, 45%)"
                  fillOpacity={0.15}
                  name="Importe Acumulado"
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <p className="py-12 text-center text-muted-foreground">{t("common.no_data")}</p>
          )}
        </CardContent>
      </Card>

      {/* Heatmap: Month x Estado */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Heatmap: Mes x Estado</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[300px] w-full" />
          ) : heatmapData && heatmapData.meses.length > 0 && heatmapData.estados.length > 0 ? (
            <div className="overflow-x-auto">
              <div className="inline-block min-w-full">
                {/* Header row: month labels */}
                <div className="flex">
                  <div className="w-32 shrink-0" />
                  {heatmapData.meses.map((mes) => (
                    <div
                      key={mes}
                      className="w-14 shrink-0 text-center text-xs text-muted-foreground truncate px-0.5"
                      title={mes}
                    >
                      {mes.length > 7 ? mes.slice(5) : mes}
                    </div>
                  ))}
                </div>

                {/* Rows: one per estado */}
                {heatmapData.estados.map((estado) => (
                  <div key={estado} className="flex items-center">
                    <div className="w-32 shrink-0 text-xs text-muted-foreground truncate pr-2" title={estado}>
                      {estado}
                    </div>
                    {heatmapData.meses.map((mes) => {
                      const cell = heatmapData.grid.find(
                        (g) => g.mes === mes && g.estado === estado,
                      );
                      const value = cell?.value ?? 0;
                      return (
                        <div
                          key={`${estado}-${mes}`}
                          className={cn(
                            "w-14 h-8 shrink-0 m-0.5 rounded-sm flex items-center justify-center text-[10px] font-medium transition-colors",
                            getHeatmapColor(value, heatmapData.maxVal),
                            value > 0 ? "text-white" : "text-muted-foreground",
                          )}
                          title={`${estado} - ${mes}: ${value}`}
                        >
                          {value > 0 ? value : ""}
                        </div>
                      );
                    })}
                  </div>
                ))}

                {/* Legend */}
                <div className="flex items-center gap-2 mt-4">
                  <span className="text-xs text-muted-foreground">Menos</span>
                  {HEATMAP_COLORS.map((color, i) => (
                    <div key={i} className={cn("w-6 h-4 rounded-sm", color)} />
                  ))}
                  <span className="text-xs text-muted-foreground">Mas</span>
                </div>
              </div>
            </div>
          ) : (
            <p className="py-12 text-center text-muted-foreground">{t("common.no_data")}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
