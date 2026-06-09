"use client";
import { EmptyState } from "@/components/ui/empty-state";

import { useState, useMemo } from "react";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useSortToggle } from "@/hooks/use-sort-toggle";
import { KpiCard } from "@/components/charts/kpi-card";
import { ExportPopover } from "@/components/export-popover";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { formatCurrency, formatNumber, formatPercent, truncate } from "@/lib/utils";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";
import {
  Trophy,
  Hash,
  Target,
  Info,
  ArrowUpDown,
  Search,
  MapPin,
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
  Legend,
  LineChart,
  Line,
  ComposedChart,
} from "recharts";

const MONTH_LABELS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

interface Competitor {
  nombre: string;
  nif?: string;
  count: number;
  importe: number;
  cuota: number;
  contratos_por_anio?: number;
  importe_medio?: number;
  baja_media?: number;
}

interface HeatmapEntry {
  ccaa: string;
  empresa: string;
  count: number;
}

interface EstacionalidadEntry {
  mes: number;
  count: number;
  importe: number;
}

interface CompetitorsData {
  total_adjudicaciones: number;
  hhi: number;
  pct_oferta_unica: number;
  pct_pyme: number;
  top_competidor: string;
  competitors: Competitor[];
  heatmap_ccaa?: HeatmapEntry[];
  estacionalidad?: EstacionalidadEntry[];
}

type SortKey = "nombre" | "nif" | "count" | "importe" | "cuota" | "contratos_por_anio" | "importe_medio" | "baja_media";

export default function LicitadoresPage() {
  const { data, isLoading, error } = useFilteredQuery<CompetitorsData>(
    ["analytics", "competitors", "licitadores"],
    "/api/v1/analytics/competitors",
    { staleTime: 5 * 60 * 1000 },
  );

  const [search, setSearch] = useState("");
  const { sortKey, sortDir, toggleSort } = useSortToggle<SortKey>("count");
  const [activeTab, setActiveTab] = useState<"ranking" | "geografia" | "evolucion">("ranking");
  const [topN, setTopN] = useState(20);

  const filteredCompetitors = useMemo(() => {
    if (!data?.competitors) return [];
    if (!search) return data.competitors;
    const q = search.toLowerCase();
    return data.competitors.filter((c) => c.nombre.toLowerCase().includes(q));
  }, [data, search]);

  const filteredSorted = useMemo(() => {
    return [...filteredCompetitors].sort((a, b) => {
      const mul = sortDir === "asc" ? 1 : -1;
      if (sortKey === "nombre" || sortKey === "nif") {
        return mul * (a[sortKey] ?? "").localeCompare(b[sortKey] ?? "");
      }
      return mul * ((a[sortKey] ?? 0) - (b[sortKey] ?? 0));
    });
  }, [filteredCompetitors, sortKey, sortDir]);

  // Bar chart filtered
  const barData = useMemo(() => {
    return [...filteredCompetitors].sort((a, b) => b.count - a.count).slice(0, topN);
  }, [filteredCompetitors, topN]);

  // Estacionalidad monthly
  const estacionalidadData = useMemo(() => {
    if (!data?.estacionalidad?.length) return [];
    return Array.from({ length: 12 }, (_, i) => {
      const entry = data.estacionalidad!.find((e) => e.mes === i + 1);
      return { mes: MONTH_LABELS[i], count: entry?.count ?? 0, importe: entry?.importe ?? 0 };
    });
  }, [data]);

  // Geography: aggregate adjudicaciones by CCAA from heatmap
  const geoByCcaa = useMemo(() => {
    if (!data?.heatmap_ccaa?.length) return [];
    const agg: Record<string, { count: number; importe: number }> = {};
    for (const cell of data.heatmap_ccaa) {
      if (!agg[cell.ccaa]) agg[cell.ccaa] = { count: 0, importe: 0 };
      agg[cell.ccaa].count += cell.count;
    }
    return Object.entries(agg)
      .map(([ccaa, vals]) => ({ ccaa, count: vals.count }))
      .sort((a, b) => b.count - a.count);
  }, [data]);

  // Evolution: aggregate by importe ranges for top competitors
  const evolutionData = useMemo(() => {
    if (!filteredCompetitors.length) return [];
    return [...filteredCompetitors]
      .sort((a, b) => b.importe - a.importe)
      .slice(0, 10)
      .map((c) => ({
        nombre: truncate(c.nombre, 25),
        importe: c.importe,
        count: c.count,
        importe_medio: c.importe_medio ?? 0,
      }));
  }, [filteredCompetitors]);

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
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
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Licitadores</h1>
          <p className="text-muted-foreground">
            Ranking de empresas licitadoras.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <SearchAutocomplete
            className="w-full sm:w-72"
            placeholder="Buscar licitador..."
            value={search}
            onChange={setSearch}
            suggestions={data?.competitors?.map((c) => c.nombre) ?? []}
            leftIcon={<Search className="h-4 w-4" />}
            inputClassName="pl-9"
          />
          <ExportPopover extraParams={{ section: "licitadores" }} />
        </div>
      </div>

      {/* Info Banner */}
      <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950/30">
        <Info className="mt-0.5 h-5 w-5 shrink-0 text-blue-600 dark:text-blue-400" />
        <div className="text-sm text-blue-800 dark:text-blue-300">
          <p className="font-medium">Datos basados en adjudicaciones</p>
          <p className="mt-1 text-blue-700/80 dark:text-blue-400/80">
            Datos de ofertas (licitaciones presentadas sin adjudicacion) se integraran en futuras versiones.
            Actualmente se muestran las empresas que han resultado adjudicatarias.
          </p>
        </div>
      </div>

      {/* Tab Toggle */}
      <div className="flex items-center gap-1 rounded-lg border p-1 w-fit">
        {(
          [
            ["ranking", "Ranking"],
            ["geografia", "Geografía"],
            ["evolucion", "Evolución"],
          ] as const
        ).map(([key, label]) => (
          <Button
            key={key}
            size="sm"
            variant={activeTab === key ? "default" : "ghost"}
            className="h-8 px-4 text-sm"
            onClick={() => setActiveTab(key)}
          >
            {label}
          </Button>
        ))}
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <KpiCard
          title="Total Licitadores"
          value={isLoading ? undefined : formatNumber(data?.competitors.length)}
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title="Total Adjudicaciones"
          value={isLoading ? undefined : formatNumber(data?.total_adjudicaciones)}
          icon={Trophy}
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
          icon={Target}
          loading={isLoading}
        />
        <KpiCard
          title="% PYME"
          value={isLoading ? undefined : formatPercent(data?.pct_pyme ?? 0)}
          icon={Trophy}
          loading={isLoading}
        />
      </div>

      {/* Bar Chart: Top licitadores by count */}
      {activeTab === "ranking" && (
      <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Top {topN} Licitadores (por adjudicaciones)</CardTitle>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Top</span>
              <input
                type="range"
                aria-label="Top N licitadores"
                min={5}
                max={50}
                step={5}
                value={topN}
                onChange={(e) => setTopN(Number(e.target.value))}
                className="w-24 accent-primary"
              />
              <Badge variant="secondary" className="text-xs">{topN}</Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[500px] w-full" />
          ) : barData.length > 0 ? (
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
                <Bar dataKey="count" fill="hsl(160, 60%, 45%)" radius={[0, 4, 4, 0]} name="Adjudicaciones" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Ranking de Licitadores</CardTitle>
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
              <Table>
                <TableHeader>
                  <TableRow className="text-left text-muted-foreground">
                    <TableHead className="w-10">#</TableHead>
                    {TABLE_COLUMNS.map(({ key, label }) => (
                      <TableHead
                        key={key}
                        className="cursor-pointer select-none hover:text-foreground whitespace-nowrap"
                        onClick={() => toggleSort(key)}
                        tabIndex={0}
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
                    <TableRow key={idx}>
                      <TableCell className="text-muted-foreground tabular-nums">{idx + 1}</TableCell>
                      <TableCell className="font-medium">{c.nombre}</TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">{c.nif ?? "-"}</TableCell>
                      <TableCell className="tabular-nums">{formatNumber(c.count)}</TableCell>
                      <TableCell className="tabular-nums">{formatCurrency(c.importe)}</TableCell>
                      <TableCell className="tabular-nums">{formatPercent(c.cuota)}</TableCell>
                      <TableCell className="tabular-nums">{c.contratos_por_anio != null ? formatNumber(c.contratos_por_anio) : "-"}</TableCell>
                      <TableCell className="tabular-nums">{c.importe_medio != null ? formatCurrency(c.importe_medio) : "-"}</TableCell>
                      <TableCell className="tabular-nums">{c.baja_media != null ? formatPercent(c.baja_media) : "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="py-8 text-center text-muted-foreground">
              {search ? "No se encontraron licitadores" : "Sin datos disponibles"}
            </p>
          )}
          {!isLoading && filteredSorted.length > 0 && (
            <>
              <Separator className="my-3" />
              <p className="text-xs text-muted-foreground">
                Mostrando {filteredSorted.length} de {data?.competitors.length ?? 0} licitadores
              </p>
            </>
          )}
        </CardContent>
      </Card>
      </>
      )}

      {/* Geography Tab */}
      {activeTab === "geografia" && (
      <>
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <MapPin className="h-4 w-4" />
            Adjudicaciones por CCAA
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : geoByCcaa.length > 0 ? (
            <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={Math.max(300, geoByCcaa.length * 30)}>
              <BarChart
                data={geoByCcaa}
                layout="vertical"
                margin={{ left: 140 }}
              >
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis type="number" tick={{ fontSize: 12 }} />
                <YAxis
                  dataKey="ccaa"
                  type="category"
                  tick={{ fontSize: 11 }}
                  width={130}
                />
                <Tooltip formatter={(v) => [formatNumber(v as number), "Adjudicaciones"]} />
                <Bar dataKey="count" fill={CHART_SERIES[0]} radius={[0, 4, 4, 0]} name="Adjudicaciones" />
              </BarChart>
            </ResponsiveContainer>
            </ChartErrorBoundary>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>
      </>
      )}

      {/* Evolution Tab — Estacionalidad Mensual */}
      {activeTab === "evolucion" && (
      <>
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Estacionalidad Mensual
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : estacionalidadData.length > 0 ? (
            <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={350}>
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
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      {/* Top 10 Importe — kept as secondary */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Top 10 por Importe</CardTitle>
        </CardHeader>
        <CardContent>
          {!isLoading && evolutionData.length > 0 ? (
            <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={Math.max(350, evolutionData.length * 35)}>
              <BarChart
                data={evolutionData}
                layout="vertical"
                margin={{ left: 160, right: 20 }}
              >
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v: number) => formatCurrency(v)} />
                <YAxis dataKey="nombre" type="category" tick={{ fontSize: 11 }} width={150} />
                <Tooltip formatter={(v) => [formatCurrency(v as number), "Importe"]} />
                <Bar dataKey="importe" fill={CHART_SERIES[0]} name="Importe Total" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
            </ChartErrorBoundary>
          ) : (
            <Skeleton className="h-[300px] w-full" />
          )}
        </CardContent>
      </Card>
      </>
      )}
    </div>
  );
}
