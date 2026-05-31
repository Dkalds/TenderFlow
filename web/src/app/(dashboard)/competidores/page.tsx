"use client";

import React, { useState, useMemo, useCallback } from "react";
import dynamic from "next/dynamic";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import { KpiCard } from "@/components/charts/kpi-card";
const RadarChart = dynamic(() => import("@/components/charts/radar-chart").then(m => ({ default: m.RadarChart })), { ssr: false });
import { ExportPopover } from "@/components/export-popover";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Checkbox } from "@/components/ui/checkbox";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { formatCurrency, formatNumber, formatPercent, truncate, cn } from "@/lib/utils";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";
import {
  Swords,
  Hash,
  Target,
  AlertTriangle,
  Crown,
  ArrowUpDown,
  Search,
  Users,
  Building2,
  TrendingUp,
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
  ScatterChart,
  Scatter,
  ZAxis,
  Label,
  LabelList,
  Treemap,
  Legend,
  LineChart,
  Line,
  ComposedChart,
} from "recharts";


interface Competitor {
  nombre: string;
  nif?: string;
  count: number;
  importe: number;
  cuota: number;
  contratos_por_anio?: number;
  importe_medio?: number;
  baja_media?: number;
  n_organos?: number;
  ofertas_medias?: number;
  pct_monopolio?: number;
  pct_top_organo?: number;
  ultima?: string;
}

interface EstacionalidadEntry {
  mes: number;
  count: number;
  importe: number;
}

interface ScatterPoint {
  nombre: string;
  ticket_medio: number;
  n_organos: number;
}

interface HeatmapEntry {
  ccaa: string;
  empresa: string;
  count: number;
}

interface CompetitorsData {
  total_adjudicaciones: number;
  hhi: number;
  pct_oferta_unica: number;
  pct_pyme: number;
  top_competidor: string;
  competitors: Competitor[];
  scatter_data?: ScatterPoint[];
  heatmap_ccaa?: HeatmapEntry[];
  estacionalidad?: EstacionalidadEntry[];
}

type SortKey = "nombre" | "count" | "importe" | "cuota" | "contratos_por_anio" | "importe_medio" | "baja_media" | "nif" | "ofertas_medias" | "pct_monopolio" | "pct_top_organo" | "ultima";

const MONTH_LABELS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];
type SortDir = "asc" | "desc";

// Heatmap color scale
function heatColor(value: number, max: number): string {
  if (max === 0) return "transparent";
  const intensity = value / max;
  const alpha = Math.max(0.08, intensity);
  return `rgba(37, 99, 235, ${alpha})`;
}

export default function CompetidoresPage() {
  const { data, isLoading, error } = useFilteredQuery<CompetitorsData>(
    ["analytics", "competitors"],
    "/api/v1/analytics/competitors",
    { staleTime: 5 * 60 * 1000 },
  );

  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("count");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [selectedCompanies, setSelectedCompanies] = useState<string[]>([]);
  const [drillDownCompany, setDrillDownCompany] = useState<Competitor | null>(null);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const toggleCompareSelection = useCallback((nombre: string) => {
    setSelectedCompanies((prev) => {
      if (prev.includes(nombre)) return prev.filter((n) => n !== nombre);
      if (prev.length >= 2) return [prev[1], nombre];
      return [...prev, nombre];
    });
  }, []);

  // Apply search filter to all data
  const searchFilter = useCallback(
    (items: { nombre: string }[]) => {
      if (!search) return items;
      const q = search.toLowerCase();
      return items.filter((c) => c.nombre.toLowerCase().includes(q));
    },
    [search],
  );

  const filteredCompetitors = useMemo(() => {
    if (!data?.competitors) return [];
    return searchFilter(data.competitors) as Competitor[];
  }, [data, searchFilter]);

  const filteredSorted = useMemo(() => {
    return [...filteredCompetitors].sort((a, b) => {
      const mul = sortDir === "asc" ? 1 : -1;
      if (sortKey === "nombre" || sortKey === "nif" || sortKey === "ultima") {
        return mul * ((a[sortKey] ?? "") as string).localeCompare((b[sortKey] ?? "") as string);
      }
      return mul * (((a[sortKey] as number) ?? 0) - ((b[sortKey] as number) ?? 0));
    });
  }, [filteredCompetitors, sortKey, sortDir]);

  // Pie chart: top 10 + Otros by importe (filtered)
  const pieData = useMemo(() => {
    if (!filteredCompetitors.length) return [];
    const sorted = [...filteredCompetitors].sort((a, b) => b.importe - a.importe);
    const top10 = sorted.slice(0, 10);
    const otrosImporte = sorted.slice(10).reduce((s, c) => s + c.importe, 0);
    const result = top10.map((c) => ({ name: truncate(c.nombre, 25), value: c.importe }));
    if (otrosImporte > 0) result.push({ name: "Otros", value: otrosImporte });
    return result;
  }, [filteredCompetitors]);

  // Top 20 bar chart data (filtered)
  const barData = useMemo(() => {
    return [...filteredCompetitors].sort((a, b) => b.count - a.count).slice(0, 20);
  }, [filteredCompetitors]);

  // Scatter data filtered
  const scatterData = useMemo(() => {
    if (!data?.scatter_data) return [];
    return searchFilter(data.scatter_data) as ScatterPoint[];
  }, [data, searchFilter]);

  // Top 5 for scatter labels
  const scatterTop5 = useMemo(() => {
    if (!data?.competitors) return new Set<string>();
    const top = [...data.competitors].sort((a, b) => b.importe - a.importe).slice(0, 5);
    return new Set(top.map((c) => c.nombre));
  }, [data]);

  // Heatmap
  const heatmapData = useMemo(() => {
    if (!data?.heatmap_ccaa?.length) return { empresas: [] as string[], ccaas: [] as string[], matrix: {} as Record<string, Record<string, number>>, max: 0 };
    const filtered = search
      ? data.heatmap_ccaa.filter((h) => h.empresa.toLowerCase().includes(search.toLowerCase()))
      : data.heatmap_ccaa;

    // Top 10 empresas by total count
    const empresaCounts: Record<string, number> = {};
    for (const h of filtered) {
      empresaCounts[h.empresa] = (empresaCounts[h.empresa] ?? 0) + h.count;
    }
    const empresas = Object.entries(empresaCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([e]) => e);
    const empresaSet = new Set(empresas);

    const ccaaSet = new Set<string>();
    const matrix: Record<string, Record<string, number>> = {};
    let max = 0;
    for (const h of filtered) {
      if (!empresaSet.has(h.empresa)) continue;
      ccaaSet.add(h.ccaa);
      if (!matrix[h.empresa]) matrix[h.empresa] = {};
      matrix[h.empresa][h.ccaa] = h.count;
      if (h.count > max) max = h.count;
    }
    return { empresas, ccaas: Array.from(ccaaSet).sort(), matrix, max };
  }, [data, search]);

  // Radar comparison data
  const radarData = useMemo(() => {
    if (selectedCompanies.length !== 2 || !data?.competitors) return null;
    const [nameA, nameB] = selectedCompanies;
    const compA = data.competitors.find((c) => c.nombre === nameA);
    const compB = data.competitors.find((c) => c.nombre === nameB);
    if (!compA || !compB) return null;

    const allComps = data.competitors;
    const maxCount = Math.max(...allComps.map((c) => c.count), 1);
    const maxImporte = Math.max(...allComps.map((c) => c.importe), 1);
    const maxCuota = Math.max(...allComps.map((c) => c.cuota), 1);
    const maxCpa = Math.max(...allComps.map((c) => c.contratos_por_anio ?? 0), 1);
    const maxIm = Math.max(...allComps.map((c) => c.importe_medio ?? 0), 1);

    const dims = ["Contratos", "Importe", "Cuota", "Contratos/Año", "Importe Medio", "Competitividad"];
    const normalize = (c: Competitor) => [
      (c.count / maxCount) * 100,
      (c.importe / maxImporte) * 100,
      (c.cuota / maxCuota) * 100,
      ((c.contratos_por_anio ?? 0) / maxCpa) * 100,
      ((c.importe_medio ?? 0) / maxIm) * 100,
      100 - (c.baja_media ?? 0),
    ];

    const valsA = normalize(compA);
    const valsB = normalize(compB);

    return {
      nameA,
      nameB,
      dataA: dims.map((d, i) => ({ dimension: d, value: valsA[i] })),
      dataB: dims.map((d, i) => ({ dimension: d, value: valsB[i] })),
    };
  }, [selectedCompanies, data]);

  // Treemap: top 20 companies by importe for sector visualization
  const treemapData = useMemo(() => {
    if (!filteredCompetitors.length) return [];
    return [...filteredCompetitors]
      .sort((a, b) => b.importe - a.importe)
      .slice(0, 20)
      .map((c) => ({
        name: truncate(c.nombre, 22),
        size: c.importe,
        count: c.count,
      }));
  }, [filteredCompetitors]);

  // Estacionalidad: top 5 companies key metrics comparison
  const seasonalityData = useMemo(() => {
    if (!filteredCompetitors.length) return [];
    const top5 = [...filteredCompetitors].sort((a, b) => b.count - a.count).slice(0, 5);
    return top5.map((c) => ({
      nombre: truncate(c.nombre, 20),
      contratos_anio: c.contratos_por_anio ?? 0,
      importe_medio: c.importe_medio ?? 0,
      baja_media: c.baja_media ?? 0,
    }));
  }, [filteredCompetitors]);

  // Positioning scatter: baja_media vs importe_medio
  const positioningData = useMemo(() => {
    if (!filteredCompetitors.length) return [];
    return filteredCompetitors
      .filter((c) => c.baja_media != null && c.importe_medio != null && c.importe_medio > 0)
      .map((c) => ({
        nombre: c.nombre,
        baja_media: c.baja_media ?? 0,
        importe_medio: c.importe_medio ?? 0,
        count: c.count,
        pct_monopolio: c.pct_monopolio ?? 0,
      }));
  }, [filteredCompetitors]);

  // Estacionalidad monthly chart data
  const estacionalidadData = useMemo(() => {
    if (!data?.estacionalidad?.length) return [];
    const full = Array.from({ length: 12 }, (_, i) => {
      const entry = data.estacionalidad!.find((e) => e.mes === i + 1);
      return { mes: MONTH_LABELS[i], count: entry?.count ?? 0, importe: entry?.importe ?? 0 };
    });
    return full;
  }, [data]);

  // Drill-down CCAA breakdown for selected company
  const drillDownCcaa = useMemo(() => {
    if (!drillDownCompany || !data?.heatmap_ccaa) return [];
    return data.heatmap_ccaa
      .filter((h) => h.empresa === drillDownCompany.nombre)
      .sort((a, b) => b.count - a.count);
  }, [drillDownCompany, data]);

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  const TABLE_COLUMNS: { key: SortKey; label: string }[] = [
    { key: "nombre", label: "Nombre" },
    { key: "nif", label: "NIF" },
    { key: "count", label: "Adjudicaciones" },
    { key: "importe", label: "Importe" },
    { key: "cuota", label: "Cuota %" },
    { key: "contratos_por_anio", label: "Contratos/Año" },
    { key: "importe_medio", label: "Importe Medio" },
    { key: "baja_media", label: "Baja Media %" },
    { key: "ofertas_medias", label: "Ofertas Medias" },
    { key: "pct_monopolio", label: "% Monopolio" },
    { key: "pct_top_organo", label: "% Top Organo" },
    { key: "ultima", label: "Ultima Adj." },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Competidores</h1>
          <p className="text-muted-foreground">
            Cuota de mercado de empresas competidoras.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative w-full sm:w-72">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Buscar empresa..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8"
            />
          </div>
          <ExportPopover extraParams={{ section: "competitors" }} />
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Total Adjudicaciones"
          value={isLoading ? undefined : formatNumber(data?.total_adjudicaciones)}
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title="HHI Concentracion"
          value={isLoading ? undefined : formatNumber(data?.hhi)}
          subtitle={
            data?.hhi != null
              ? data.hhi < 1500
                ? "Mercado competitivo"
                : data.hhi < 2500
                  ? "Concentracion moderada"
                  : "Mercado concentrado"
              : undefined
          }
          icon={Target}
          loading={isLoading}
        />
        <KpiCard
          title="% Oferta Unica"
          value={isLoading ? undefined : formatPercent(data?.pct_oferta_unica)}
          icon={AlertTriangle}
          loading={isLoading}
        />
        <KpiCard
          title="Top Competidor"
          value={isLoading ? undefined : truncate(data?.top_competidor ?? data?.competitors?.[0]?.nombre ?? "-", 30)}
          icon={Crown}
          loading={isLoading}
        />
      </div>

      {/* Charts Row 1: Bar + Pie */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Horizontal Bar: Top 20 by count */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Top 20 Competidores (por adjudicaciones)</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[500px] w-full" />
            ) : barData.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={Math.max(400, barData.length * 32)}>
                <BarChart
                  data={barData}
                  layout="vertical"
                  margin={{ left: 180 }}
                >
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis type="number" tick={{ fontSize: 12 }} />
                  <YAxis
                    dataKey="nombre"
                    type="category"
                    tick={{ fontSize: 11 }}
                    width={170}
                    tickFormatter={(v: string) => truncate(v, 30)}
                  />
                  <Tooltip formatter={(v) => formatNumber(v as number)} />
                  <Bar dataKey="count" fill={CHART_SERIES[0]} radius={[0, 4, 4, 0]} name="Adjudicaciones" />
                </BarChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos disponibles</p>
            )}
          </CardContent>
        </Card>

        {/* Pie: Market share by importe */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Cuota de Mercado por Importe (Top 10)</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : pieData.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={400}>
                <PieChart>
                  <Pie
                    data={pieData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={140}
                    label={({ name, percent }: { name?: string; percent?: number }) =>
                      `${name ?? ""}: ${((percent ?? 0) * 100).toFixed(1)}%`
                    }
                    labelLine={{ strokeWidth: 1 }}
                  >
                    {pieData.map((_, idx) => (
                      <Cell key={idx} fill={getSeriesColor(idx)} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v) => formatCurrency(v as number)} />
                </PieChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos disponibles</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Charts Row 2: Scatter + Heatmap */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Scatter: ticket_medio vs n_organos */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Ticket Medio vs Dependencia de Clientes</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : scatterData.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={400}>
                <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis
                    type="number"
                    dataKey="ticket_medio"
                    name="Ticket Medio"
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v: number) => formatCurrency(v)}
                  >
                    <Label value="Ticket Medio" position="bottom" offset={0} style={{ fontSize: 12 }} />
                  </XAxis>
                  <YAxis
                    type="number"
                    dataKey="n_organos"
                    name="Organos"
                    tick={{ fontSize: 11 }}
                  >
                    <Label value="N. Organos" angle={-90} position="left" offset={0} style={{ fontSize: 12 }} />
                  </YAxis>
                  <ZAxis range={[40, 400]} />
                  <Tooltip
                    cursor={{ strokeDasharray: "3 3" }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const d = payload[0].payload as ScatterPoint;
                      return (
                        <div className="rounded-md border bg-popover px-3 py-2 text-sm text-popover-foreground shadow-md">
                          <p className="font-medium">{d.nombre}</p>
                          <p>Ticket medio: {formatCurrency(d.ticket_medio)}</p>
                          <p>Organos: {formatNumber(d.n_organos)}</p>
                        </div>
                      );
                    }}
                  />
                  <Scatter
                    data={scatterData}
                    fill={CHART_SERIES[0]}
                    fillOpacity={0.7}
                  >
                    <LabelList
                      dataKey="nombre"
                      position="top"
                      style={{ fontSize: 12 }}
                      content={({ x, y, value }) => {
                        if (!scatterTop5.has(value as string)) return null;
                        return (
                          <text x={x as number} y={(y as number) - 8} textAnchor="middle" fontSize={12} fill="hsl(var(--foreground))">
                            {truncate(value as string, 18)}
                          </text>
                        );
                      }}
                    />
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos de scatter disponibles</p>
            )}
          </CardContent>
        </Card>

        {/* CCAA x Empresa Heatmap */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Actividad por CCAA y Empresa</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : heatmapData.empresas.length > 0 ? (
              <div className="overflow-x-auto">
                <div
                  className="grid gap-px text-xs"
                  style={{
                    gridTemplateColumns: `180px repeat(${heatmapData.ccaas.length}, minmax(50px, 1fr))`,
                  }}
                >
                  {/* Header row */}
                  <div className="font-medium text-muted-foreground p-1" />
                  {heatmapData.ccaas.map((ccaa) => (
                    <div key={ccaa} className="font-medium text-muted-foreground p-1 text-center truncate" title={ccaa}>
                      {truncate(ccaa, 10)}
                    </div>
                  ))}
                  {/* Data rows */}
                  {heatmapData.empresas.map((empresa) => (
                    <React.Fragment key={empresa}>
                      <div key={`label-${empresa}`} className="font-medium p-1 truncate" title={empresa}>
                        {truncate(empresa, 25)}
                      </div>
                      {heatmapData.ccaas.map((ccaa) => {
                        const val = heatmapData.matrix[empresa]?.[ccaa] ?? 0;
                        return (
                          <div
                            key={`${empresa}-${ccaa}`}
                            className="p-1 text-center rounded-sm cursor-default transition-colors"
                            style={{ backgroundColor: heatColor(val, heatmapData.max) }}
                            title={`${empresa} - ${ccaa}: ${val}`}
                          >
                            {val > 0 ? val : ""}
                          </div>
                        );
                      })}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos de heatmap disponibles</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Charts Row 3: Treemap + Top 5 Metrics */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Cuota de Mercado (Treemap Top 20)</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : treemapData.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={400}>
                <Treemap
                  data={treemapData}
                  dataKey="size"
                  nameKey="name"
                  aspectRatio={4 / 3}
                  stroke="hsl(var(--border))"
                  content={({ x, y, width, height, name, value, index }: any) => {
                    const showLabel = width > 50 && height > 30;
                    return (
                      <g>
                        <rect
                          x={x}
                          y={y}
                          width={width}
                          height={height}
                          fill={getSeriesColor(index ?? 0)}
                          stroke="hsl(var(--border))"
                          strokeWidth={1}
                          rx={2}
                        />
                        {showLabel && (
                          <>
                            <text
                              x={x + width / 2}
                              y={y + height / 2 - 6}
                              textAnchor="middle"
                              fill="white"
                              fontSize={11}
                              fontWeight={500}
                            >
                              {name}
                            </text>
                            <text
                              x={x + width / 2}
                              y={y + height / 2 + 10}
                              textAnchor="middle"
                              fill="rgba(255,255,255,0.75)"
                              fontSize={10}
                            >
                              {formatCurrency(value as number)}
                            </text>
                          </>
                        )}
                      </g>
                    );
                  }}
                >
                  <Tooltip
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const d = payload[0].payload;
                      return (
                        <div className="rounded-md border bg-popover px-3 py-2 text-sm shadow-md">
                          <p className="font-medium">{d.name}</p>
                          <p>Importe: {formatCurrency(d.size)}</p>
                          <p>Adjudicaciones: {formatNumber(d.count)}</p>
                        </div>
                      );
                    }}
                  />
                </Treemap>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos disponibles</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Posicionamiento Competitivo</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : positioningData.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={400}>
                <ScatterChart margin={{ top: 20, right: 20, bottom: 30, left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis
                    type="number"
                    dataKey="baja_media"
                    name="Baja Media"
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v: number) => `${v.toFixed(0)}%`}
                  >
                    <Label value="Baja Media %" position="bottom" offset={10} style={{ fontSize: 12 }} />
                  </XAxis>
                  <YAxis
                    type="number"
                    dataKey="importe_medio"
                    name="Importe Medio"
                    tick={{ fontSize: 11 }}
                    scale="log"
                    domain={["auto", "auto"]}
                    tickFormatter={(v: number) => formatCurrency(v)}
                  >
                    <Label value="Importe Medio (log)" angle={-90} position="left" offset={0} style={{ fontSize: 12 }} />
                  </YAxis>
                  <ZAxis dataKey="count" range={[40, 600]} name="Contratos" />
                  <Tooltip
                    cursor={{ strokeDasharray: "3 3" }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const d = payload[0].payload as (typeof positioningData)[0];
                      return (
                        <div className="rounded-md border bg-popover px-3 py-2 text-sm text-popover-foreground shadow-md">
                          <p className="font-medium">{d.nombre}</p>
                          <p>Baja media: {d.baja_media.toFixed(1)}%</p>
                          <p>Importe medio: {formatCurrency(d.importe_medio)}</p>
                          <p>Contratos: {formatNumber(d.count)}</p>
                          <p>% Monopolio: {d.pct_monopolio.toFixed(1)}%</p>
                        </div>
                      );
                    }}
                  />
                  <Scatter data={positioningData} fill={CHART_SERIES[2]} fillOpacity={0.7}>
                    <LabelList
                      dataKey="nombre"
                      position="top"
                      content={({ x, y, value }) => {
                        const top5Names = new Set(
                          [...positioningData].sort((a, b) => b.count - a.count).slice(0, 5).map((d) => d.nombre),
                        );
                        if (!top5Names.has(value as string)) return null;
                        return (
                          <text x={x as number} y={(y as number) - 8} textAnchor="middle" fontSize={10} fill="hsl(var(--foreground))">
                            {truncate(value as string, 18)}
                          </text>
                        );
                      }}
                    />
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos de posicionamiento (requiere baja media)</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Estacionalidad Mensual */}
      {estacionalidadData.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Estacionalidad Mensual</CardTitle>
          </CardHeader>
          <CardContent>
            <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={estacionalidadData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="mes" tick={{ fontSize: 12 }} />
                <YAxis yAxisId="left" tick={{ fontSize: 12 }} />
                <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} tickFormatter={(v: number) => formatCurrency(v)} />
                <Tooltip
                  formatter={(v, name) =>
                    name === "Importe" ? formatCurrency(Number(v ?? 0)) : formatNumber(Number(v ?? 0))
                  }
                />
                <Legend />
                <Bar yAxisId="left" dataKey="count" fill={CHART_SERIES[0]} radius={[4, 4, 0, 0]} name="Adjudicaciones" />
                <Line yAxisId="right" type="monotone" dataKey="importe" stroke={CHART_SERIES[1]} strokeWidth={2} dot={{ r: 3 }} name="Importe" />
              </ComposedChart>
            </ResponsiveContainer>
            </ChartErrorBoundary>
          </CardContent>
        </Card>
      )}

      {/* Radar Comparator */}
      {radarData && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Users className="h-4 w-4" />
              Comparacion: {truncate(radarData.nameA, 25)} vs {truncate(radarData.nameB, 25)}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <RadarChart
              data={radarData.dataA}
              name={truncate(radarData.nameA, 20)}
              compareData={radarData.dataB}
              compareName={truncate(radarData.nameB, 20)}
              height={400}
            />
          </CardContent>
        </Card>
      )}

      {selectedCompanies.length > 0 && selectedCompanies.length < 2 && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-300">
          Selecciona 1 empresa mas en la tabla para comparar con radar. ({selectedCompanies.length}/2 seleccionadas)
        </div>
      )}

      {/* Table */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle className="text-base">Todos los Competidores</CardTitle>
            <p className="text-xs text-muted-foreground">
              Selecciona 2 empresas para comparar con radar
            </p>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : filteredSorted.length > 0 ? (
            <div className="overflow-x-auto">
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow className="border-b text-left text-muted-foreground">
                    <TableHead className="px-2 py-2 font-medium w-10">
                      <span className="sr-only">Comparar</span>
                    </TableHead>
                    {TABLE_COLUMNS.map(({ key, label }) => (
                      <TableHead
                        key={key}
                        className="cursor-pointer select-none px-3 py-2 font-medium hover:text-foreground whitespace-nowrap"
                        tabIndex={0}
                        role="columnheader"
                        aria-sort={sortKey === key ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                        onClick={() => toggleSort(key)}
                        onKeyDown={(e) => { if (e.key === "Enter") toggleSort(key); }}
                      >
                        <span className="inline-flex items-center gap-1">
                          {label}
                          <ArrowUpDown className="h-3 w-3" />
                          {sortKey === key && (
                            <Badge variant="secondary" className="ml-1 text-xs px-1 py-0">
                              {sortDir === "asc" ? "ASC" : "DESC"}
                            </Badge>
                          )}
                        </span>
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredSorted.map((c, idx) => (
                    <TableRow key={idx} className="border-b last:border-0 hover:bg-muted/50">
                      <TableCell className="px-2 py-2">
                        <Checkbox
                          className="h-5 w-5"
                          checked={selectedCompanies.includes(c.nombre)}
                          onCheckedChange={() => toggleCompareSelection(c.nombre)}
                        />
                      </TableCell>
                      <TableCell
                        className="px-3 py-2 font-medium cursor-pointer hover:underline text-primary"
                        onClick={() => setDrillDownCompany(c)}
                      >
                        {c.nombre}
                      </TableCell>
                      <TableCell className="px-3 py-2 tabular-nums text-muted-foreground">{c.nif ?? "-"}</TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">{formatNumber(c.count)}</TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">{formatCurrency(c.importe)}</TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">{formatPercent(c.cuota)}</TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">{c.contratos_por_anio != null ? formatNumber(c.contratos_por_anio) : "-"}</TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">{c.importe_medio != null ? formatCurrency(c.importe_medio) : "-"}</TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">{c.baja_media != null ? formatPercent(c.baja_media) : "-"}</TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">{c.ofertas_medias != null ? c.ofertas_medias.toFixed(1) : "-"}</TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">{c.pct_monopolio != null ? formatPercent(c.pct_monopolio) : "-"}</TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">{c.pct_top_organo != null ? formatPercent(c.pct_top_organo) : "-"}</TableCell>
                      <TableCell className="px-3 py-2 tabular-nums text-muted-foreground">{c.ultima ?? "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="py-8 text-center text-muted-foreground">
              {search ? "No se encontraron competidores" : "Sin datos disponibles"}
            </p>
          )}
          {!isLoading && filteredSorted.length > 0 && (
            <>
              <Separator className="my-3" />
              <p className="text-xs text-muted-foreground">
                Mostrando {filteredSorted.length} de {data?.competitors.length ?? 0} competidores
              </p>
            </>
          )}
        </CardContent>
      </Card>

      {/* Drill-down Sheet */}
      <Sheet open={!!drillDownCompany} onOpenChange={(open) => !open && setDrillDownCompany(null)}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>{drillDownCompany?.nombre}</SheetTitle>
          </SheetHeader>
          {drillDownCompany && (
            <div className="mt-6 space-y-4">
              {drillDownCompany.nif && (
                <Badge variant="outline">NIF: {drillDownCompany.nif}</Badge>
              )}
              {drillDownCompany.ultima && (
                <p className="text-xs text-muted-foreground">Ultima adjudicacion: {drillDownCompany.ultima}</p>
              )}
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Adjudicaciones</p>
                  <p className="text-lg font-bold">{formatNumber(drillDownCompany.count)}</p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Importe Total</p>
                  <p className="text-lg font-bold">{formatCurrency(drillDownCompany.importe)}</p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Cuota</p>
                  <p className="text-lg font-bold">{formatPercent(drillDownCompany.cuota)}</p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Baja Media</p>
                  <p className="text-lg font-bold">
                    {drillDownCompany.baja_media != null ? formatPercent(drillDownCompany.baja_media) : "-"}
                  </p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Contratos/Año</p>
                  <p className="text-lg font-bold">
                    {drillDownCompany.contratos_por_anio != null ? formatNumber(drillDownCompany.contratos_por_anio) : "-"}
                  </p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Importe Medio</p>
                  <p className="text-lg font-bold">
                    {drillDownCompany.importe_medio != null ? formatCurrency(drillDownCompany.importe_medio) : "-"}
                  </p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">% Monopolio</p>
                  <p className="text-lg font-bold">{formatPercent(drillDownCompany.pct_monopolio ?? 0)}</p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Ofertas Medias</p>
                  <p className="text-lg font-bold">{drillDownCompany.ofertas_medias?.toFixed(1) ?? "-"}</p>
                </div>
              </div>

              {/* CCAA breakdown */}
              {drillDownCcaa.length > 0 && (
                <>
                  <Separator />
                  <div>
                    <p className="text-sm font-medium mb-2">Actividad por CCAA</p>
                    <div className="space-y-1">
                      {drillDownCcaa.slice(0, 8).map((h) => {
                        const maxCount = drillDownCcaa[0]?.count ?? 1;
                        return (
                          <div key={h.ccaa} className="flex items-center gap-2 text-sm">
                            <span className="w-32 truncate text-muted-foreground">{h.ccaa}</span>
                            <div className="flex-1 h-4 bg-muted rounded-full overflow-hidden">
                              <div
                                className="h-full bg-primary rounded-full"
                                style={{ width: `${(h.count / maxCount) * 100}%` }}
                              />
                            </div>
                            <span className="tabular-nums text-xs w-8 text-right">{h.count}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </>
              )}

              <Separator />
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-muted-foreground">N. Organos</p>
                  <p className="font-medium">{formatNumber(drillDownCompany.n_organos ?? 0)}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">% Top Organo</p>
                  <p className="font-medium">{formatPercent(drillDownCompany.pct_top_organo ?? 0)}</p>
                </div>
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
