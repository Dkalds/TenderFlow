"use client";

import { useState, useMemo } from "react";
import dynamic from "next/dynamic";
import { KpiCard } from "@/components/charts/kpi-card";
import { MiniSparkline } from "@/components/charts/mini-sparkline";
const SankeyChart = dynamic(
  () => import("@/components/charts/sankey-chart").then((m) => ({ default: m.SankeyChart })),
  { ssr: false },
);
import { ExportPopover } from "@/components/export-popover";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { t } from "@/lib/i18n";
import { cn, formatCurrency, formatNumber, truncate } from "@/lib/utils";
import { CHART_SERIES, getSeriesColor, getEstadoChartColor } from "@/lib/chart-colors";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import {
  BarChart3,
  Building2,
  DollarSign,
  TrendingUp,
  Hash,
  Calendar,
  Flame,
  Clock,
  Activity,
  Info,
  MapPin,
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
} from "recharts";
import { TimelineSection } from "./_components/timeline-section";
import { MarketIndicators } from "./_components/market-indicators";
import { PeriodComparison } from "./_components/period-comparison";
import { FunnelEstados } from "./_components/funnel-estados";
import type { TimelineItem, CompareResponse, ExtendedOverview } from "./_components/types";
import { ITEMS_PER_PAGE } from "./_components/types";

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

// --- Local types (not shared) ---

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

interface TecnologiasResponse {
  tecnologias: { tecnologia: string; count: number; importe: number; pct: number }[];
  sin_clasificar: number;
}

interface TiposProyectoResponse {
  tipos_proyecto: { tipo: string; count: number; importe: number }[];
  modulos: { modulo: string; count: number; importe: number }[];
  total_clasificados: number;
}

export default function ResumenPage() {
  const { comparar, setComparar, rango, rangoB } = useFilters();
  const [pubPage, setPubPage] = useState(0);
  const [pubSortKey, setPubSortKey] = useState<keyof TimelineItem>("fecha_publicacion");
  const [pubSortDir, setPubSortDir] = useState<"asc" | "desc">("desc");

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

  // Default timeline to last 30 days when no date filter is set
  const timelineDesde = rango.desde ?? new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
  const timeline = useFilteredQuery<TimelineResponse>(
    ["analytics", "resumen", "timeline", timelineDesde],
    "/api/v1/analytics/resumen/timeline",
    { staleTime: 5 * 60 * 1000 },
    { fecha_desde: timelineDesde },
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

  // Timeline scatter data
  const scatterData =
    timeline.data?.items?.map((item) => ({
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

  // Pagination + sorting for ultimas publicaciones
  const sortedPubs = useMemo(() => {
    const items = [...(timeline.data?.items ?? [])];
    items.sort((a, b) => {
      const av = a[pubSortKey];
      const bv = b[pubSortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") return pubSortDir === "asc" ? av - bv : bv - av;
      const cmp = String(av).localeCompare(String(bv), "es", { sensitivity: "base" });
      return pubSortDir === "asc" ? cmp : -cmp;
    });
    return items;
  }, [timeline.data?.items, pubSortKey, pubSortDir]);

  const togglePubSort = (key: keyof TimelineItem) => {
    if (pubSortKey === key) {
      setPubSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setPubSortKey(key);
      setPubSortDir("asc");
    }
    setPubPage(0);
  };

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
          <CardContent className="flex items-center justify-center py-4" style={{ paddingTop: "1rem" }}>
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
          value={
            isLoading
              ? undefined
              : `${formatNumber(data?.concentracion_geo_top3 != null ? Math.round((data.concentracion_geo_top3 / 100) * 17) : undefined)}/17`
          }
          subtitle="Cobertura geografica"
          icon={MapPin}
          loading={isLoading}
        />
      </div>

      {/* 4. Timeline scatter + Últimas Publicaciones */}
      <TimelineSection
        scatterData={scatterData}
        sortedPubs={sortedPubs}
        isLoading={timeline.isLoading}
        pubPage={pubPage}
        setPubPage={setPubPage}
        pubSortKey={pubSortKey}
        pubSortDir={pubSortDir}
        togglePubSort={togglePubSort}
      />

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
                <div
                  key={item.id_externo}
                  className="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
                >
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
                <ResponsiveContainer width="100%" height={Math.max(300, tiposData.length * 36)}>
                  <BarChart data={tiposData} layout="vertical" margin={{ left: 120 }}>
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

      {/* 8. Market Indicators */}
      <MarketIndicators data={data} isLoading={isLoading} />

      {/* 9. Period comparison */}
      <PeriodComparison
        comparar={comparar}
        setComparar={setComparar}
        rango={rango}
        rangoB={rangoB}
        compare={compare}
      />

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
                    <Bar
                      dataKey="n_licitaciones"
                      fill={CHART_SERIES[0]}
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
          </CardHeader>
          <CardContent>
            {tecnologias.isLoading ? (
              <Skeleton className="h-[300px] w-full" />
            ) : techData.length > 0 ? (
              <ChartErrorBoundary>
                <ResponsiveContainer width="100%" height={Math.max(300, techData.length * 32)}>
                  <BarChart data={techData} layout="vertical" margin={{ left: 100 }}>
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
      <FunnelEstados funnelEstados={data?.funnel_estados ?? []} />
    </div>
  );
}
