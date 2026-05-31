"use client";

import { useState, useMemo } from "react";
import dynamic from "next/dynamic";
import { KpiCard } from "@/components/charts/kpi-card";
import { MiniSparkline } from "@/components/charts/mini-sparkline";
const SankeyChart = dynamic(() => import("@/components/charts/sankey-chart").then(m => ({ default: m.SankeyChart })), { ssr: false });
import { ExportPopover } from "@/components/export-popover";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { t } from "@/lib/i18n";
import { cn, formatCurrency, formatNumber, formatPercent, formatDate, truncate } from "@/lib/utils";
import { CHART_SERIES, getSeriesColor, getEstadoChartColor } from "@/lib/chart-colors";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import type { AnalyticsOverview } from "@/generated/api";
import {
  BarChart3,
  Building2,
  DollarSign,
  TrendingDown,
  TrendingUp,
  Hash,
  Calendar,
  Flame,
  Clock,
  Activity,
  ArrowUpDown,
  Info,
  MapPin,
  ChevronLeft,
  ChevronRight,
  Users,
  Lock,
  Timer,
  Globe,
  Cpu,
} from "lucide-react";
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
  AreaChart,
  Area,
  ScatterChart,
  Scatter,
  ZAxis,
} from "recharts";

// --- Helpers ---

/** Anomaly detection: |current - mean| >= sigma * stddev */
function isAnomaly(current: number, history: number[], sigma = 2.0): boolean {
  if (history.length < 3) return false;
  const mean = history.reduce((a, b) => a + b, 0) / history.length;
  const variance = history.reduce((a, b) => a + (b - mean) ** 2, 0) / history.length;
  const std = Math.sqrt(variance);
  const threshold = std > 0 ? sigma * std : mean * 0.1;
  return Math.abs(current - mean) >= threshold;
}

// --- Types ---

interface NovedadesResponse {
  count: number;
  sample: { id_externo: string; titulo: string; importe: number | null; organo_contratacion: string }[];
}

interface HoyResponse {
  calientes: number;
  vencen_48h: number;
  nuevas_24h: number;
  total_activas: number;
}

interface TimelineItem {
  id_externo: string;
  titulo: string;
  importe: number | null;
  fecha_publicacion: string;
  estado: string;
}

interface TimelineResponse {
  items: TimelineItem[];
}

interface SankeyResponse {
  nodes: { id: string; label: string }[];
  links: { source: string; target: string; value: number }[];
}

interface TopItem {
  id_externo: string;
  titulo: string;
  organo_contratacion: string;
  importe: number | null;
  estado: string;
  adjudicatario: string | null;
  baja_pct: number | null;
}

interface TopResponse {
  items: TopItem[];
}

interface CompareResponse {
  period_a: Record<string, number>;
  period_b: Record<string, number>;
  deltas: Record<string, number>;
}

interface TecnologiasResponse {
  tecnologias: { tecnologia: string; count: number; importe: number; pct: number }[];
  sin_clasificar: number;
}

interface TiposProyectoResponse {
  tipos_proyecto: { tipo: string; count: number; importe: number }[];
  modulos: { modulo: string; count: number; importe: number }[];
  total_clasificados: number;
}

type ExtendedOverview = AnalyticsOverview;

const ITEMS_PER_PAGE = 10;

export default function ResumenPage() {
  const { comparar, setComparar, rango, rangoB } = useFilters();
  const [pubPage, setPubPage] = useState(0);

  // --- Data fetching ---
  const overview = useFilteredQuery<ExtendedOverview>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    { staleTime: 5 * 60 * 1000 },
  );

  const novedades = useFilteredQuery<NovedadesResponse>(
    ["analytics", "resumen", "novedades"],
    "/api/v1/analytics/resumen/novedades",
    { staleTime: 5 * 60 * 1000 },
  );

  const hoy = useFilteredQuery<HoyResponse>(
    ["analytics", "resumen", "hoy"],
    "/api/v1/analytics/resumen/hoy",
    { staleTime: 2 * 60 * 1000 },
  );

  const sankey = useFilteredQuery<SankeyResponse>(
    ["analytics", "resumen", "sankey"],
    "/api/v1/analytics/resumen/sankey",
    { staleTime: 5 * 60 * 1000 },
  );

  const timeline = useFilteredQuery<TimelineResponse>(
    ["analytics", "resumen", "timeline"],
    "/api/v1/analytics/resumen/timeline",
    { staleTime: 5 * 60 * 1000 },
  );

  const top = useFilteredQuery<TopResponse>(
    ["analytics", "resumen", "top"],
    "/api/v1/analytics/resumen/top",
    { staleTime: 5 * 60 * 1000 },
  );

  const compare = useFilteredQuery<CompareResponse>(
    ["analytics", "compare-periods", rango.desde ?? "", rango.hasta ?? "", rangoB.desde ?? "", rangoB.hasta ?? ""],
    "/api/v1/analytics/compare-periods",
    {
      staleTime: 5 * 60 * 1000,
      enabled: comparar && !!rango.desde && !!rangoB.desde,
    },
  );

  const tecnologias = useFilteredQuery<TecnologiasResponse>(
    ["analytics", "tecnologias"],
    "/api/v1/analytics/tecnologias",
    { staleTime: 5 * 60 * 1000 },
  );

  const tiposProyecto = useFilteredQuery<TiposProyectoResponse>(
    ["analytics", "proyectos-modulos"],
    "/api/v1/analytics/proyectos-modulos",
    { staleTime: 5 * 60 * 1000 },
  );

  const data = overview.data;
  const isLoading = overview.isLoading;

  // --- Derived sparkline series from por_mes ---
  const sparklines = useMemo(() => {
    const porMes = data?.por_mes;
    if (!porMes || porMes.length < 2) return null;
    return {
      count: porMes.map((m) => m.n_licitaciones),
      importe: porMes.map((m) => m.importe),
    };
  }, [data?.por_mes]);

  // Anomaly flags for main KPIs
  const anomalyFlags = useMemo(() => {
    if (!sparklines) return { count: false, importe: false };
    const countSeries = sparklines.count;
    const importeSeries = sparklines.importe;
    const lastCount = countSeries[countSeries.length - 1];
    const lastImporte = importeSeries[importeSeries.length - 1];
    return {
      count: isAnomaly(lastCount, countSeries.slice(0, -1)),
      importe: isAnomaly(lastImporte, importeSeries.slice(0, -1)),
    };
  }, [sparklines]);

  // Critical error
  if (overview.error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
        <p className="text-destructive">
          {t("common.error")}: {(overview.error as Error).message}
        </p>
      </div>
    );
  }

  // HHI color helper
  const hhiColor = (v: number | null | undefined) => {
    if (v == null) return "text-muted-foreground";
    if (v < 1500) return "text-green-600";
    if (v < 2500) return "text-yellow-600";
    return "text-red-600";
  };

  // Timeline scatter data
  const scatterData = timeline.data?.items?.map((item) => ({
    x: new Date(item.fecha_publicacion).getTime(),
    y: item.importe ?? 0,
    z: item.importe ?? 0,
    titulo: item.titulo,
    estado: item.estado,
    fill: getEstadoChartColor(item.estado),
  })) ?? [];

  // Activity: last 12 months from por_mes
  const activityData = data?.por_mes?.slice(-12) ?? [];

  // Tipos de proyecto sorted
  const tiposData = useMemo(() => {
    const raw = tiposProyecto.data?.tipos_proyecto;
    if (!raw) return [];
    return [...raw].sort((a, b) => a.count - b.count);
  }, [tiposProyecto.data]);

  // Tecnologías top 10
  const techData = useMemo(() => {
    const raw = tecnologias.data?.tecnologias;
    if (!raw) return [];
    return [...raw].sort((a, b) => b.count - a.count).slice(0, 10);
  }, [tecnologias.data]);

  // Pagination for ultimas publicaciones
  const allPubs = timeline.data?.items ?? [];
  const totalPubPages = Math.max(1, Math.ceil(allPubs.length / ITEMS_PER_PAGE));
  const pagedPubs = allPubs.slice(pubPage * ITEMS_PER_PAGE, (pubPage + 1) * ITEMS_PER_PAGE);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Resumen</h1>
          <p className="text-muted-foreground">
            Top licitaciones, distribucion por estado y salud competitiva del mercado.
          </p>
        </div>
        <ExportPopover />
      </div>

      {/* 1. Novedades banner */}
      {novedades.isLoading ? (
        <Skeleton className="h-20 w-full" />
      ) : novedades.data && novedades.data.count > 0 ? (
        <Card className="border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950">
          <CardContent className="py-4">
            <div className="flex items-start gap-3">
              <Info className="mt-0.5 h-5 w-5 text-blue-600 dark:text-blue-400 shrink-0" />
              <div className="space-y-2">
                <p className="font-medium text-blue-900 dark:text-blue-100">
                  {novedades.data.count} nuevas licitaciones desde tu ultima visita
                </p>
                <ul className="space-y-1 text-sm text-blue-800 dark:text-blue-200">
                  {novedades.data.sample.slice(0, 5).map((item) => (
                    <li key={item.id_externo} className="flex items-center justify-between gap-4">
                      <span className="truncate">{truncate(item.titulo, 60)}</span>
                      {item.importe != null && (
                        <span className="shrink-0 font-medium">{formatCurrency(item.importe)}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : novedades.data ? (
        <Card className="border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950">
          <CardContent className="py-4">
            <p className="text-green-800 dark:text-green-200 text-sm font-medium">Todo al dia</p>
          </CardContent>
        </Card>
      ) : null}

      {/* 2. Para hoy KPI row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Nuevas 24h"
          value={hoy.isLoading ? undefined : formatNumber(hoy.data?.nuevas_24h)}
          icon={Flame}
          loading={hoy.isLoading}
          sparkline={sparklines ? <MiniSparkline data={sparklines.count} up /> : undefined}
          anomaly={anomalyFlags.count}
        />
        <KpiCard
          title="Vencen 48h"
          value={hoy.isLoading ? undefined : formatNumber(hoy.data?.vencen_48h)}
          icon={Clock}
          loading={hoy.isLoading}
          className={hoy.data && hoy.data.vencen_48h > 0 ? "border-destructive/50" : undefined}
        />
        <KpiCard
          title="Calientes"
          value={hoy.isLoading ? undefined : formatNumber(hoy.data?.calientes)}
          icon={Flame}
          loading={hoy.isLoading}
        />
        <KpiCard
          title="Total activas"
          value={hoy.isLoading ? undefined : formatNumber(hoy.data?.total_activas)}
          icon={Activity}
          loading={hoy.isLoading}
        />
      </div>

      {/* 3. Main KPIs row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <KpiCard
          title={t("kpi.total_licitaciones")}
          value={isLoading ? undefined : formatNumber(data?.total_licitaciones)}
          icon={Hash}
          loading={isLoading}
          sparkline={sparklines ? <MiniSparkline data={sparklines.count} up /> : undefined}
          anomaly={anomalyFlags.count}
        />
        <KpiCard
          title={t("kpi.importe_total")}
          value={isLoading ? undefined : formatCurrency(data?.importe_total)}
          icon={DollarSign}
          loading={isLoading}
          sparkline={sparklines ? <MiniSparkline data={sparklines.importe} up /> : undefined}
          anomaly={anomalyFlags.importe}
        />
        <KpiCard
          title={t("kpi.importe_medio")}
          value={isLoading ? undefined : formatCurrency(data?.importe_medio)}
          icon={BarChart3}
          loading={isLoading}
        />
        <KpiCard
          title={t("kpi.organos_unicos")}
          value={isLoading ? undefined : formatNumber(data?.organos_unicos)}
          icon={Building2}
          trend={data?.yoy_delta}
          loading={isLoading}
        />
        <KpiCard
          title="CCAA cubiertas"
          value={isLoading ? undefined : `${formatNumber(data?.concentracion_geo_top3 != null ? Math.round(data.concentracion_geo_top3 / 100 * 17) : undefined)}/17`}
          subtitle="Cobertura geografica"
          icon={MapPin}
          loading={isLoading}
        />
      </div>

      {/* 4. Timeline scatter */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Timeline de Publicaciones</CardTitle>
        </CardHeader>
        <CardContent>
          {timeline.isLoading ? (
            <Skeleton className="h-[380px] w-full" />
          ) : scatterData.length > 0 ? (
            <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={380}>
              <ScatterChart margin={{ top: 10, right: 10, bottom: 10, left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis
                  dataKey="x"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(v: number) => new Date(v).toLocaleDateString("es-ES", { month: "short", day: "numeric" })}
                  tick={{ fontSize: 12 }}
                  name="Fecha"
                />
                <YAxis
                  dataKey="y"
                  type="number"
                  tickFormatter={(v: number) => formatCurrency(v)}
                  tick={{ fontSize: 12 }}
                  name="Importe"
                  width={80}
                />
                <ZAxis dataKey="z" range={[30, 250]} />
                <Tooltip
                  content={({ payload }) => {
                    if (!payload?.[0]) return null;
                    const d = payload[0].payload as (typeof scatterData)[0];
                    return (
                      <div className="rounded bg-popover p-2 text-xs shadow border border-border">
                        <p className="font-medium">{truncate(d.titulo, 50)}</p>
                        <p>{formatCurrency(d.y)}</p>
                        <p className="text-muted-foreground">{d.estado}</p>
                      </div>
                    );
                  }}
                />
                <Scatter data={scatterData} fill={CHART_SERIES[0]}>
                  {scatterData.map((entry, idx) => (
                    <Cell key={idx} fill={entry.fill} />
                  ))}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
            </ChartErrorBoundary>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      {/* Últimas Publicaciones (paginated) */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Ultimas Publicaciones</CardTitle>
            {allPubs.length > ITEMS_PER_PAGE && (
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  disabled={pubPage === 0}
                  onClick={() => setPubPage((p) => Math.max(0, p - 1))}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {pubPage + 1} / {totalPubPages}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  disabled={pubPage >= totalPubPages - 1}
                  onClick={() => setPubPage((p) => Math.min(totalPubPages - 1, p + 1))}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {timeline.isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : pagedPubs.length > 0 ? (
            <div className="divide-y">
              {pagedPubs.map((item) => (
                <div key={item.id_externo} className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm truncate">{truncate(item.titulo, 60)}</p>
                    <p className="text-xs text-muted-foreground">{formatDate(item.fecha_publicacion)}</p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-sm font-medium tabular-nums">{formatCurrency(item.importe)}</span>
                    <Badge variant="outline" className="text-xs">{item.estado}</Badge>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      {/* 5. Top 10 licitaciones */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Top 10 Licitaciones</CardTitle>
        </CardHeader>
        <CardContent>
          {top.isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : top.data?.items && top.data.items.length > 0 ? (
            <div className="divide-y">
              {top.data.items.map((item) => (
                <div key={item.id_externo} className="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-sm truncate">{truncate(item.titulo, 80)}</p>
                    <p className="text-xs text-muted-foreground truncate">{item.organo_contratacion}</p>
                    {item.adjudicatario && (
                      <p className="text-xs text-muted-foreground">Adj: {item.adjudicatario}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="font-semibold text-sm tabular-nums">
                      {formatCurrency(item.importe)}
                    </span>
                    <Badge variant="secondary">{item.estado}</Badge>
                    {item.baja_pct != null && (
                      <Badge variant="outline" className="text-xs">
                        -{item.baja_pct.toFixed(1)}%
                      </Badge>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      {/* 6. Distribucion por Estado (donut) + Tipos de Proyecto (bar) */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Distribucion por Estado</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[320px] w-full" />
            ) : data?.por_estado && data.por_estado.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={320}>
                <PieChart>
                  <Pie
                    data={data.por_estado}
                    dataKey="n"
                    nameKey="estado"
                    cx="50%"
                    cy="50%"
                    outerRadius={110}
                    innerRadius={55}
                    label={({ name, value }: { name?: string; value?: number }) =>
                      `${name ?? ""}: ${value ?? 0}`
                    }
                  >
                    {data.por_estado.map((_, idx) => (
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
            {tiposProyecto.isLoading ? (
              <Skeleton className="h-[320px] w-full" />
            ) : tiposData.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer
                width="100%"
                height={Math.max(300, tiposData.length * 36)}
              >
                <BarChart
                  data={tiposData}
                  layout="vertical"
                  margin={{ left: 120 }}
                >
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
                  <Bar
                    dataKey="count"
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
      </div>

      {/* 7. Sankey */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Flujo Tipo → Estado</CardTitle>
        </CardHeader>
        <CardContent>
          {sankey.isLoading ? (
            <Skeleton className="h-[420px] w-full" />
          ) : sankey.data?.nodes && sankey.data.nodes.length > 0 ? (
            <SankeyChart
              nodes={sankey.data.nodes}
              links={sankey.data.links}
              className="h-[420px]"
            />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      {/* 8. Market Indicators — 2 groups */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Indicadores de Mercado</h3>
        <div className="grid gap-3 grid-cols-2 md:grid-cols-3">
          {([
            {
              label: "% PYMEs adjudicadas",
              value: data?.pct_pyme != null ? formatPercent(data.pct_pyme) : "-",
              color: data?.pct_pyme != null && data.pct_pyme >= 40 ? "text-green-600" : data?.pct_pyme != null && data.pct_pyme < 20 ? "text-red-600" : "text-foreground",
              icon: Users,
            },
            {
              label: "Concentracion top 10",
              value: data?.concentracion_top10 != null ? formatPercent(data.concentracion_top10) : "-",
              color: data?.concentracion_top10 != null && data.concentracion_top10 < 60 ? "text-green-600" : data?.concentracion_top10 != null && data.concentracion_top10 >= 80 ? "text-red-600" : "text-foreground",
              icon: BarChart3,
            },
            {
              label: "Tasa anulacion",
              value: data?.tasa_anulacion != null ? formatPercent(data.tasa_anulacion) : "-",
              color: data?.tasa_anulacion != null && data.tasa_anulacion > 10 ? "text-red-600" : "text-foreground",
              icon: TrendingDown,
            },
          ] as const).map((metric) => (
            <Card key={metric.label} className="p-3">
              <div className="flex items-center gap-2 mb-1">
                <metric.icon className="h-3.5 w-3.5 text-muted-foreground" />
                <p className="text-xs text-muted-foreground">{metric.label}</p>
              </div>
              <div className={cn("text-lg font-semibold", isLoading ? "" : metric.color)}>
                {isLoading ? <Skeleton className="h-6 w-16" /> : metric.value}
              </div>
            </Card>
          ))}
        </div>

        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider pt-2">Salud Competitiva</h3>
        <div className="grid gap-3 grid-cols-2 md:grid-cols-3">
          {([
            {
              label: "Lead time pub→adj",
              value: data?.lead_time_medio != null ? `${formatNumber(data.lead_time_medio)} dias` : "N/A",
              color: "text-foreground",
              icon: Timer,
            },
            {
              label: "HHI Concentracion",
              value: data?.hhi != null ? formatNumber(data.hhi) : "-",
              color: hhiColor(data?.hhi),
              subtitle: data?.hhi != null
                ? data.hhi < 1500 ? "Competitivo" : data.hhi < 2500 ? "Moderado" : "Concentrado"
                : undefined,
              icon: BarChart3,
            },
            {
              label: "% Oferta unica",
              value: data?.pct_oferta_unica != null ? formatPercent(data.pct_oferta_unica) : "-",
              color: data?.pct_oferta_unica != null && data.pct_oferta_unica < 20 ? "text-green-600" : data?.pct_oferta_unica != null && data.pct_oferta_unica >= 40 ? "text-red-600" : "text-foreground",
              icon: Lock,
            },
          ] as const).map((metric) => (
            <Card key={metric.label} className="p-3">
              <div className="flex items-center gap-2 mb-1">
                <metric.icon className="h-3.5 w-3.5 text-muted-foreground" />
                <p className="text-xs text-muted-foreground">{metric.label}</p>
              </div>
              <div className={cn("text-lg font-semibold", isLoading ? "" : metric.color)}>
                {isLoading ? <Skeleton className="h-6 w-16" /> : metric.value}
              </div>
              {"subtitle" in metric && metric.subtitle && !isLoading && (
                <p className="text-[10px] text-muted-foreground mt-0.5">{metric.subtitle}</p>
              )}
            </Card>
          ))}
        </div>
      </div>

      {/* 9. Period comparison */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Comparar Periodos</CardTitle>
            <Button
              variant={comparar ? "default" : "outline"}
              size="sm"
              onClick={() => setComparar(!comparar)}
            >
              <ArrowUpDown className="mr-2 h-4 w-4" />
              {comparar ? "Desactivar" : "Comparar"}
            </Button>
          </div>
        </CardHeader>
        {comparar && (
          <CardContent>
            {!rango.desde || !rangoB.desde ? (
              <p className="text-sm text-muted-foreground py-4">
                Selecciona dos rangos de fechas en los filtros globales para comparar.
              </p>
            ) : compare.isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : compare.data ? (
              <div className="overflow-x-auto">
                <Table className="w-full text-sm">
                  <TableHeader>
                    <TableRow className="border-b">
                      <TableHead className="text-left py-2 font-medium">Metrica</TableHead>
                      <TableHead className="text-right py-2 font-medium">Periodo A</TableHead>
                      <TableHead className="text-right py-2 font-medium">Periodo B</TableHead>
                      <TableHead className="text-right py-2 font-medium">Delta %</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {Object.keys(compare.data.deltas).map((key) => (
                      <TableRow key={key} className="border-b last:border-0">
                        <TableCell className="py-2 text-muted-foreground">{key.replace(/_/g, " ")}</TableCell>
                        <TableCell className="py-2 text-right tabular-nums">
                          {formatNumber(compare.data!.period_a[key])}
                        </TableCell>
                        <TableCell className="py-2 text-right tabular-nums">
                          {formatNumber(compare.data!.period_b[key])}
                        </TableCell>
                        <TableCell className={cn(
                          "py-2 text-right tabular-nums font-medium",
                          compare.data!.deltas[key] >= 0 ? "text-green-600" : "text-red-600",
                        )}>
                          {compare.data!.deltas[key] >= 0 ? "+" : ""}
                          {compare.data!.deltas[key].toFixed(1)}%
                          <span className="sr-only">{compare.data!.deltas[key] >= 0 ? "(subida)" : "(bajada)"}</span>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        )}
      </Card>

      {/* 10. Activity + Tecnologías */}
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
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis dataKey="mes" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip
                    formatter={(value, name) => {
                      if (name === "Importe") return [formatCurrency(value as number), name];
                      return [formatNumber(value as number), name];
                    }}
                  />
                  <Bar dataKey="n_licitaciones" fill={CHART_SERIES[0]} radius={[4, 4, 0, 0]} name="Licitaciones" />
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
          </CardHeader>
          <CardContent>
            {tecnologias.isLoading ? (
              <Skeleton className="h-[300px] w-full" />
            ) : techData.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer
                width="100%"
                height={Math.max(300, techData.length * 32)}
              >
                <BarChart
                  data={techData}
                  layout="vertical"
                  margin={{ left: 100 }}
                >
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

      {/* 11. Evolucion Mensual area chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Evolucion Mensual</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[300px] w-full" />
          ) : data?.por_mes && data.por_mes.length > 0 ? (
            <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={data.por_mes}>
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

      {/* 13. Top organos bar chart */}
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
          ) : data?.top_organos && data.top_organos.length > 0 ? (
            <ChartErrorBoundary>
            <ResponsiveContainer
              width="100%"
              height={Math.max(300, data.top_organos.length * 40)}
            >
              <BarChart
                data={data.top_organos.slice(0, 15)}
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

      {/* 14. Funnel Estados */}
      {data?.funnel_estados && data.funnel_estados.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Funnel de Estados</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {data.funnel_estados.map((item, idx) => {
                const maxN = Math.max(...data.funnel_estados.map((f) => f.n));
                const pct = maxN > 0 ? (item.n / maxN) * 100 : 0;
                return (
                  <div key={idx} className="flex items-center gap-3">
                    <span className="w-32 text-sm text-muted-foreground truncate">
                      {item.estado}
                    </span>
                    <div className="flex-1 h-6 bg-muted rounded-sm overflow-hidden">
                      <div
                        className="h-full rounded-sm transition-all"
                        style={{
                          width: `${pct}%`,
                          backgroundColor: getSeriesColor(idx),
                        }}
                      />
                    </div>
                    <Badge variant="secondary" className="tabular-nums">
                      {formatNumber(item.n)}
                    </Badge>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
