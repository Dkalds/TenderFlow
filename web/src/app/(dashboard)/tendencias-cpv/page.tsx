"use client";

import { useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { EmptyState } from "@/components/ui/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { t } from "@/lib/i18n";
import { formatCurrency, formatNumber } from "@/lib/utils";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { BarChart3 } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  AreaChart,
  Area,
} from "recharts";

/* ── Types ──────────────────────────────────────────────────────────── */

interface CpvSeriesPoint {
  period: string;
  count: number;
  importe: number;
}

interface CpvSeries {
  cpv: string;
  label: string;
  series: CpvSeriesPoint[];
}

interface TopCpv {
  cpv: string;
  importe_total: number;
  count: number;
}

interface TrendsCpvResponse {
  series_by_cpv: CpvSeries[];
  top_cpv_by_importe: TopCpv[];
  summary: Record<string, unknown>;
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

/* ── Component ──────────────────────────────────────────────────────── */

export default function TendenciasCpvPage() {
  const [selectedCpvs, setSelectedCpvs] = useState<Set<string>>(new Set());
  const [showForecast, setShowForecast] = useState(false);

  const { data: cpvData, isLoading, error } = useFilteredQuery<TrendsCpvResponse>(
    ["analytics", "trends-cpv"],
    "/api/v1/analytics/trends-cpv",
    { staleTime: 5 * 60_000 },
  );

  const { data: forecast, isLoading: forecastLoading } = useFilteredQuery<ForecastResponse>(
    ["analytics", "forecast", "volume"],
    "/api/v1/analytics/forecast/volume?months_ahead=6",
    { staleTime: 5 * 60_000, enabled: showForecast },
  );

  const allCpvs = useMemo(() => cpvData?.series_by_cpv ?? [], [cpvData]);
  const topCpvs = useMemo(() => cpvData?.top_cpv_by_importe?.slice(0, 15) ?? [], [cpvData]);

  // Initialize selection to first 3 CPVs
  const effectiveCpvs = useMemo(() => {
    if (selectedCpvs.size > 0) return selectedCpvs;
    return new Set(allCpvs.slice(0, 3).map((c) => c.cpv));
  }, [selectedCpvs, allCpvs]);

  const toggleCpv = (cpv: string) => {
    setSelectedCpvs((prev) => {
      const next = new Set(prev.size > 0 ? prev : effectiveCpvs);
      if (next.has(cpv)) next.delete(cpv);
      else next.add(cpv);
      return next;
    });
  };

  // Build merged chart data: period -> { period, cpv1, cpv2, ... }
  const chartData = useMemo(() => {
    const selected = allCpvs.filter((c) => effectiveCpvs.has(c.cpv));
    if (selected.length === 0) return [];

    const periodMap = new Map<string, Record<string, number>>();
    for (const cpvSeries of selected) {
      for (const pt of cpvSeries.series) {
        if (!periodMap.has(pt.period)) periodMap.set(pt.period, {});
        periodMap.get(pt.period)![cpvSeries.cpv] = pt.importe;
      }
    }

    return Array.from(periodMap.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([period, vals]) => ({ period, ...vals }));
  }, [allCpvs, effectiveCpvs]);

  // Forecast overlay data
  const forecastData = useMemo(() => {
    if (!forecast?.series) return [];
    return forecast.series.map((p) => ({
      mes: p.mes,
      historico: p.tipo === "historico" ? p.valor : undefined,
      forecast_val: p.tipo === "forecast" ? p.valor : undefined,
      lower: p.tipo === "forecast" ? p.lower : undefined,
      upper: p.tipo === "forecast" ? p.upper : undefined,
    }));
  }, [forecast]);

  // CPV table data from real endpoint
  const cpvTableData = useMemo(() => {
    return topCpvs.map((item, idx) => ({
      rank: idx + 1,
      cpv: item.cpv,
      count: item.count,
      importe: item.importe_total,
    }));
  }, [topCpvs]);

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
        <h1 className="sr-only">Tendencias CPV</h1>
        <p className="text-muted-foreground">Series temporales por codigo CPV.</p>
      </div>

      {/* CPV Multiselect */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Seleccionar CPVs</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : (
            <div className="flex flex-wrap gap-2 max-h-48 overflow-y-auto">
              {allCpvs.map((cpvItem, idx) => {
                const isSelected = effectiveCpvs.has(cpvItem.cpv);
                return (
                  <label
                    key={cpvItem.cpv}
                    className="inline-flex items-center gap-1.5 cursor-pointer rounded-md border px-2.5 py-1.5 text-sm transition-colors hover:bg-muted"
                    style={isSelected ? { borderColor: getSeriesColor(idx) } : undefined}
                  >
                    <Checkbox
                      className="h-5 w-5"
                      checked={isSelected}
                      onCheckedChange={() => toggleCpv(cpvItem.cpv)}
                    />
                    <span
                      className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
                      style={{ backgroundColor: getSeriesColor(idx) }}
                    />
                    <span>{cpvItem.label || cpvItem.cpv}</span>
                  </label>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Per-CPV Line Chart */}
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
            onClick={() => setShowForecast((f) => !f)}
          >
            <BarChart3 className="h-4 w-4 mr-1" />
            Prevision
          </Button>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[350px] w-full" />
          ) : chartData.length > 0 ? (
            <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={350}>
              <LineChart accessibilityLayer data={chartData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="period" tick={{ fontSize: 12 }} angle={-45} textAnchor="end" height={60} />
                <YAxis tick={{ fontSize: 12 }} tickFormatter={(v: number) => formatCurrency(v)} />
                <Tooltip formatter={(value) => [formatCurrency(value as number), ""]} />
                {allCpvs
                  .filter((c) => effectiveCpvs.has(c.cpv))
                  .map((c, _idx) => (
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

      {/* Forecast overlay */}
      {showForecast && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <CardTitle className="text-base">Prevision Volumen (6 meses)</CardTitle>
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
            {forecastLoading ? (
              <Skeleton className="h-[300px] w-full" />
            ) : forecastData.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart accessibilityLayer data={forecastData}>
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
      )}

      {/* Top 15 CPV by Importe — Horizontal Bar Chart */}
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
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow className="border-b">
                    <TableHead className="text-left py-2 pr-4 font-medium text-muted-foreground">#</TableHead>
                    <TableHead className="text-left py-2 pr-4 font-medium text-muted-foreground">CPV</TableHead>
                    <TableHead className="text-right py-2 pr-4 font-medium text-muted-foreground">Licitaciones</TableHead>
                    <TableHead className="text-right py-2 font-medium text-muted-foreground">Importe Total</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {cpvTableData.map((row) => (
                    <TableRow
                      key={row.cpv}
                      className="border-b last:border-0 hover:bg-muted/50 cursor-pointer transition-colors"
                      tabIndex={0}
                      role="row"
                      onClick={() => toggleCpv(row.cpv)}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") toggleCpv(row.cpv); }}
                    >
                      <TableCell className="py-2 pr-4 tabular-nums text-muted-foreground">{row.rank}</TableCell>
                      <TableCell className="py-2 pr-4">
                        <div className="flex items-center gap-2">
                          <div
                            className="w-2.5 h-2.5 rounded-full shrink-0"
                            style={{ backgroundColor: getSeriesColor(row.rank - 1) }}
                          />
                          {row.cpv}
                        </div>
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">{formatNumber(row.count)}</TableCell>
                      <TableCell className="py-2 text-right tabular-nums">{formatCurrency(row.importe)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
