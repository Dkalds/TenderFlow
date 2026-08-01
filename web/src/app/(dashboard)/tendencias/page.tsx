"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { KpiCard } from "@/components/charts/kpi-card";
const WaterfallChart = dynamic(() => import("@/components/charts/waterfall-chart").then(m => ({ default: m.WaterfallChart })), { ssr: false, loading: () => <Skeleton className="h-[420px] w-full rounded-md" /> });
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";
import { formatCurrency, formatNumber, formatPercent, cn } from "@/lib/utils";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import type { TrendPoint } from "@/lib/api-types";
import {
  Hash,
  DollarSign,
  TrendingUp,
  TrendingDown,
  CalendarDays,
} from "lucide-react";
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
  Line,
} from "recharts";

/* ── Types ──────────────────────────────────────────────────────────── */

interface WaterfallPoint {
  period: string;
  delta: number;
  cumulative: number;
}

interface HistogramBin {
  bin_label: string;
  count: number;
}

interface MesPico {
  mes: string;
  importe: number;
  count: number;
}

interface TrendsResponse {
  series: TrendPoint[];
  waterfall: WaterfallPoint[];
  histogram_bins: HistogramBin[];
  mes_pico: MesPico;
}

interface OverviewResponse {
  por_estado: { estado: string; n: number }[];
  por_mes: { mes: string; n_licitaciones: number; importe: number }[];
}

interface ForecastPoint {
  mes: string;
  valor: number;
  tipo: "historico" | "forecast";
  lower?: number;
  upper?: number;
}

interface ForecastResponse {
  series: ForecastPoint[];
}

/* ── Helpers ────────────────────────────────────────────────────────── */

function computeYoY(series: TrendPoint[], field: "count" | "importe") {
  if (series.length < 13) return null;
  const recent = series.slice(-12);
  const prior = series.slice(-24, -12);
  if (prior.length === 0) return null;
  const sumRecent = recent.reduce((s, p) => s + (field === "count" ? p.count : (p.importe ?? 0)), 0);
  const sumPrior = prior.reduce((s, p) => s + (field === "count" ? p.count : (p.importe ?? 0)), 0);
  if (sumPrior === 0) return null;
  return ((sumRecent - sumPrior) / sumPrior) * 100;
}

/**
 * Heatmap intensity — returns an inline style using the primary accent token
 * with variable alpha, so the scale lives in one place and respects the theme.
 */
function heatmapCellStyle(value: number, max: number): { backgroundColor: string } {
  if (max === 0 || value === 0) {
    return { backgroundColor: "hsl(var(--muted) / 0.4)" };
  }
  const alpha = 0.12 + (value / max) * 0.83;
  return { backgroundColor: `hsl(var(--primary) / ${alpha})` };
}

/** 7-step legend swatches mirroring the cell scale above. */
const HEATMAP_LEGEND_STEPS = [0, 0.16, 0.32, 0.48, 0.64, 0.8, 0.95] as const;

/* ── Component ──────────────────────────────────────────────────────── */

export default function TendenciasPage() {
  const [forecastMetric, setForecastMetric] = useState<"count" | "sum">("count");

  const { data: trends, isLoading: trendsLoading, error: trendsError } = useFilteredQuery<TrendsResponse>(
    ["analytics", "trends"],
    "/api/v1/analytics/trends?group_by=month",
    { staleTime: 5 * 60_000 },
  );

  const { data: overview, isLoading: overviewLoading, error: overviewError } = useFilteredQuery<OverviewResponse>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    { staleTime: 5 * 60_000 },
  );

  const { data: forecast, isLoading: forecastLoading } = useFilteredQuery<ForecastResponse>(
    ["analytics", "forecast", forecastMetric],
    `/api/v1/analytics/forecast/volume?months_ahead=6&metric=${forecastMetric}`,
    { staleTime: 5 * 60_000 },
  );

  const isLoading = trendsLoading || overviewLoading;
  const error = trendsError || overviewError;
  const series = useMemo(() => trends?.series ?? [], [trends]);

  const totalCount = useMemo(() => series.reduce((s, p) => s + p.count, 0), [series]);
  const totalImporte = useMemo(() => series.reduce((s, p) => s + (p.importe ?? 0), 0), [series]);
  const yoyCount = useMemo(() => computeYoY(series, "count"), [series]);
  const yoyImporte = useMemo(() => computeYoY(series, "importe"), [series]);

  const cumulativeData = useMemo(() => {
    const result: { period: string; importe_acumulado: number }[] = [];
    let acc = 0;
    for (const p of series) {
      acc += p.importe ?? 0;
      result.push({ period: p.period, importe_acumulado: acc });
    }
    return result;
  }, [series]);

  // Heatmap — ESTIMADO (no es un cruce real): producto de marginales
  // (distribución global de estados × volumen mensual). El cruce real (mes,estado)
  // debe venir de un cross-tab en backend (ver RFC ux-tendencias). Etiquetado en UI
  // como "Estimado" mientras tanto, para no presentar síntesis como dato real.
  const heatmapData = useMemo(() => {
    if (!overview) return null;
    const estados = overview.por_estado.map((e) => e.estado);
    const meses = overview.por_mes.map((m) => m.mes);
    const totalByEstado = overview.por_estado.reduce((s, e) => s + e.n, 0);
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

  // Histogram: detect if log scale needed
  const histBins = trends?.histogram_bins ?? [];
  const histMax = Math.max(...histBins.map((b) => b.count), 1);
  const histMin = Math.min(...histBins.filter((b) => b.count > 0).map((b) => b.count), histMax);
  const useLogScale = histMax / histMin > 100;

  // Forecast chart data
  const forecastData = useMemo(() => {
    if (!forecast?.series) return [];
    return forecast.series.map((p) => ({
      ...p,
      historico: p.tipo === "historico" ? p.valor : undefined,
      forecast_val: p.tipo === "forecast" ? p.valor : undefined,
      lower: p.tipo === "forecast" ? p.lower : undefined,
      upper: p.tipo === "forecast" ? p.upper : undefined,
    }));
  }, [forecast]);

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">{t("common.error")}: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Tendencias</h1>
        <p className="text-muted-foreground">Evolucion de publicaciones y montos a lo largo del tiempo.</p>
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <KpiCard title="Total Licitaciones" value={isLoading ? undefined : formatNumber(totalCount)} icon={Hash} loading={isLoading} />
        <KpiCard title="Importe Total" value={isLoading ? undefined : formatCurrency(totalImporte)} icon={DollarSign} loading={isLoading} />
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
        {/* Mes Pico KPI */}
        <KpiCard
          title="Mes Pico"
          value={isLoading ? undefined : trends?.mes_pico ? trends.mes_pico.mes : "-"}
          subtitle={
            trends?.mes_pico
              ? `${formatCurrency(trends.mes_pico.importe)} · ${formatNumber(trends.mes_pico.count)} lic.`
              : undefined
          }
          icon={CalendarDays}
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

      {/* Area Chart: Importe acumulado */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Importe Acumulado</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[350px] w-full" />
          ) : cumulativeData.length > 0 ? (
            <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={350}>
              <AreaChart accessibilityLayer data={cumulativeData}>
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

      {/* Waterfall Chart */}
      {(trends?.waterfall?.length ?? 0) > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Waterfall: Variacion Mensual</CardTitle>
          </CardHeader>
          <CardContent>
            <WaterfallChart data={trends!.waterfall} height={320} />
          </CardContent>
        </Card>
      )}

      {/* Histogram */}
      {histBins.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Distribucion de Importes</CardTitle>
          </CardHeader>
          <CardContent>
            <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart accessibilityLayer data={histBins} layout="vertical">
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
      )}

      {/* Heatmap */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <CardTitle className="text-base">Heatmap: Mes x Estado</CardTitle>
            <Badge variant="outline" className="text-amber-600 border-amber-400">
              Estimado
            </Badge>
          </div>
          <CardDescription>
            Estimación a partir de marginales (distribución global de estados ×
            volumen mensual), no un cruce real Mes×Estado. Pendiente de exponer el
            cross-tab real en backend.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[300px] w-full" />
          ) : heatmapData && heatmapData.meses.length > 0 && heatmapData.estados.length > 0 ? (
            <div className="overflow-x-auto">
              <div className="inline-block min-w-full">
                <div className="flex">
                  <div className="w-32 shrink-0" />
                  {heatmapData.meses.map((mes) => (
                    <div key={mes} className="w-14 shrink-0 text-center text-xs text-muted-foreground truncate px-0.5" title={mes}>
                      {mes.length > 7 ? mes.slice(5) : mes}
                    </div>
                  ))}
                </div>
                {heatmapData.estados.map((estado) => (
                  <div key={estado} className="flex items-center">
                    <div className="w-32 shrink-0 text-xs text-muted-foreground truncate pr-2" title={estado}>{estado}</div>
                    {heatmapData.meses.map((mes) => {
                      const cell = heatmapData.grid.find((g) => g.mes === mes && g.estado === estado);
                      const value = cell?.value ?? 0;
                      const intensity = heatmapData.maxVal > 0 ? value / heatmapData.maxVal : 0;
                      return (
                        <div
                          key={`${estado}-${mes}`}
                          className={cn(
                            "w-14 h-8 shrink-0 m-0.5 rounded-sm flex items-center justify-center text-xs font-medium transition-colors",
                            intensity > 0.55 ? "text-primary-foreground" : "text-foreground/80",
                          )}
                          style={heatmapCellStyle(value, heatmapData.maxVal)}
                          title={`${estado} - ${mes}: ${value}`}
                        >
                          {value > 0 ? value : ""}
                        </div>
                      );
                    })}
                  </div>
                ))}
                <div className="flex items-center gap-2 mt-4">
                  <span className="text-xs text-muted-foreground">Menos</span>
                  {HEATMAP_LEGEND_STEPS.map((alpha, i) => (
                    <div
                      key={i}
                      className="w-6 h-4 rounded-sm border border-border/40"
                      style={{
                        backgroundColor:
                          alpha === 0
                            ? "hsl(var(--muted) / 0.4)"
                            : `hsl(var(--primary) / ${alpha})`,
                      }}
                    />
                  ))}
                  <span className="text-xs text-muted-foreground">Mas</span>
                </div>
              </div>
            </div>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      {/* Forecast */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">Prevision (6 meses)</CardTitle>
          <div className="flex items-center gap-1">
            <Button
              variant={forecastMetric === "count" ? "default" : "outline"}
              size="sm"
              onClick={() => setForecastMetric("count")}
            >
              Cantidad
            </Button>
            <Button
              variant={forecastMetric === "sum" ? "default" : "outline"}
              size="sm"
              onClick={() => setForecastMetric("sum")}
            >
              Importe
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {forecastLoading ? (
            <Skeleton className="h-[350px] w-full" />
          ) : forecastData.length > 0 ? (
            <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={350}>
              <AreaChart accessibilityLayer data={forecastData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="mes" tick={{ fontSize: 12 }} angle={-45} textAnchor="end" height={60} />
                <YAxis tick={{ fontSize: 12 }} tickFormatter={(v: number) => forecastMetric === "sum" ? formatCurrency(v) : formatNumber(v)} />
                <Tooltip formatter={(value) => [forecastMetric === "sum" ? formatCurrency(value as number) : formatNumber(value as number), ""]} />
                {/* Confidence band */}
                <Area type="monotone" dataKey="upper" stroke="none" fill="hsl(221, 83%, 53%)" fillOpacity={0.1} name="Upper" />
                {/* "Goma" de la banda: el token de fondo de la card (no blanco) para que sea theme-safe en dark mode. */}
                <Area type="monotone" dataKey="lower" stroke="none" fill="hsl(var(--card))" fillOpacity={1} name="Lower" />
                {/* Historical line */}
                <Line type="monotone" dataKey="historico" stroke="hsl(221, 83%, 53%)" strokeWidth={2} dot={{ r: 2 }} name="Historico" />
                {/* Forecast line */}
                <Line type="monotone" dataKey="forecast_val" stroke="hsl(221, 83%, 53%)" strokeWidth={2} strokeDasharray="6 3" dot={{ r: 2 }} name="Prevision" />
              </AreaChart>
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
