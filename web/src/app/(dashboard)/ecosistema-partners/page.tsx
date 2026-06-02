"use client";

import { useState, useMemo } from "react";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import { KpiCard } from "@/components/charts/kpi-card";
import dynamic from "next/dynamic";
import { ExportPopover } from "@/components/export-popover";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DataTable } from "@/components/ui/data-table";
import { type ColumnDef } from "@tanstack/react-table";

const ForceGraph = dynamic(() => import("@/components/charts/force-graph").then(m => ({ default: m.ForceGraph })), { ssr: false });
import {
  formatCurrency,
  formatNumber,
  formatPercent,
  truncate,
  cn,
} from "@/lib/utils";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";
import { Button } from "@/components/ui/button";
import { Network, Hash, Users, Search, Trophy, TrendingUp } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

interface Competitor {
  nombre: string;
  count: number;
  importe: number;
  cuota: number;
  nif?: string | null;
  contratos_por_anio?: number;
  importe_medio?: number;
  baja_media?: number | null;
}

interface HeatmapCell {
  ccaa: string;
  empresa: string;
  count: number;
}

interface CompetitorsData {
  total_adjudicaciones: number;
  hhi: number;
  pct_oferta_unica: number;
  pct_pyme: number;
  competitors: Competitor[];
  heatmap_ccaa: HeatmapCell[];
  scatter_data: { nombre: string; ticket_medio: number; n_organos: number }[];
}

/* ------------------------------------------------------------------ */
/*  Graph builder                                                     */
/* ------------------------------------------------------------------ */

function buildGraphData(
  competitors: Competitor[],
  heatmap: HeatmapCell[],
  highlightName: string,
) {
  const top = [...competitors]
    .sort((a, b) => b.importe - a.importe)
    .slice(0, 20);
  const nameSet = new Set(top.map((c) => c.nombre));

  // Build empresa→ccaa index from heatmap
  const empresaCcaas = new Map<string, Map<string, number>>();
  for (const cell of heatmap) {
    if (!nameSet.has(cell.empresa)) continue;
    let m = empresaCcaas.get(cell.empresa);
    if (!m) {
      m = new Map();
      empresaCcaas.set(cell.empresa, m);
    }
    m.set(cell.ccaa, (m.get(cell.ccaa) ?? 0) + cell.count);
  }

  // Assign groups by dominant CCAA
  const allCcaas: string[] = [];
  const dominantCcaa = new Map<string, string>();
  for (const [emp, ccaaMap] of empresaCcaas) {
    let best = "";
    let bestCount = 0;
    for (const [ccaa, cnt] of ccaaMap) {
      if (cnt > bestCount) {
        best = ccaa;
        bestCount = cnt;
      }
    }
    dominantCcaa.set(emp, best);
    if (best && !allCcaas.includes(best)) allCcaas.push(best);
  }

  const lowHL = highlightName.toLowerCase();
  const nodes = top.map((c) => ({
    id: c.nombre,
    label: truncate(c.nombre, 30),
    group: dominantCcaa.get(c.nombre) ?? "Otros",
    size: c.importe,
    _highlighted: lowHL ? c.nombre.toLowerCase().includes(lowHL) : false,
  }));

  // Links: co-occurrence in same CCAA
  const links: { source: string; target: string; weight: number }[] = [];
  for (let i = 0; i < top.length; i++) {
    const mapA = empresaCcaas.get(top[i].nombre);
    if (!mapA) continue;
    for (let j = i + 1; j < top.length; j++) {
      const mapB = empresaCcaas.get(top[j].nombre);
      if (!mapB) continue;
      let weight = 0;
      for (const [ccaa, countA] of mapA) {
        const countB = mapB.get(ccaa);
        if (countB) weight += Math.min(countA, countB);
      }
      if (weight > 0) {
        links.push({
          source: top[i].nombre,
          target: top[j].nombre,
          weight: Math.min(weight, 8),
        });
      }
    }
  }

  return { nodes, links };
}

/* ------------------------------------------------------------------ */
/*  Page                                                              */
/* ------------------------------------------------------------------ */

export default function EcosistemaPartnersPage() {
  const [search, setSearch] = useState("");
  const [ganadoresSearch, setGanadoresSearch] = useState("");
  const [activeTab, setActiveTab] = useState<"red" | "ganadores">("red");
  const [minWeight, setMinWeight] = useState(1);
  const [maxNodes, setMaxNodes] = useState(20);
  const { data, isLoading, error } = useFilteredQuery<CompetitorsData>(
    ["analytics", "competitors"],
    "/api/v1/analytics/competitors",
    { staleTime: 5 * 60 * 1000 },
  );

  const graph = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    const g = buildGraphData(
      data.competitors,
      data.heatmap_ccaa,
      search,
    );
    // Apply sliders: filter nodes to top maxNodes, links to minWeight
    const nodes = g.nodes.slice(0, maxNodes);
    const nodeIds = new Set(nodes.map((n) => n.id));
    const links = g.links.filter((l) => l.weight >= minWeight && nodeIds.has(l.source) && nodeIds.has(l.target));
    return { nodes, links };
  }, [data, search, minWeight, maxNodes]);

  const filteredPartners = useMemo(() => {
    if (!data?.competitors) return [];
    if (!search) return data.competitors;
    const low = search.toLowerCase();
    return data.competitors.filter((c) => c.nombre.toLowerCase().includes(low));
  }, [data, search]);

  const partnerColumns = useMemo<ColumnDef<Competitor>[]>(
    () => [
      {
        id: "rank",
        header: "#",
        cell: ({ row }) => (
          <span className="text-muted-foreground tabular-nums">{row.index + 1}</span>
        ),
        enableSorting: false,
      },
      {
        accessorKey: "nombre",
        header: "Empresa",
        cell: ({ getValue }) => (
          <span className="font-medium">{truncate(getValue<string>(), 50)}</span>
        ),
      },
      {
        accessorKey: "count",
        header: "Adj.",
        cell: ({ getValue }) => (
          <span className="tabular-nums">{formatNumber(getValue<number>())}</span>
        ),
      },
      {
        accessorKey: "importe",
        header: "Importe",
        cell: ({ getValue }) => (
          <span className="tabular-nums">{formatCurrency(getValue<number>())}</span>
        ),
      },
      {
        accessorKey: "cuota",
        header: "Cuota",
        cell: ({ getValue }) => (
          <Badge variant="secondary">{formatPercent(getValue<number>())}</Badge>
        ),
      },
      {
        accessorKey: "importe_medio",
        header: "Imp. Medio",
        cell: ({ getValue }) => {
          const v = getValue<number | undefined>();
          return <span className="tabular-nums">{v ? formatCurrency(v) : "-"}</span>;
        },
      },
      {
        accessorKey: "baja_media",
        header: "Baja Media",
        cell: ({ getValue }) => {
          const v = getValue<number | null | undefined>();
          return (
            <span className="tabular-nums">{v != null ? formatPercent(v) : "-"}</span>
          );
        },
      },
    ],
    [],
  );

  // Top CCAAs per empresa for cards
  const empresaCcaaTop = useMemo(() => {
    if (!data?.heatmap_ccaa) return new Map<string, string[]>();
    const m = new Map<string, { ccaa: string; count: number }[]>();
    for (const cell of data.heatmap_ccaa) {
      const list = m.get(cell.empresa) ?? [];
      list.push({ ccaa: cell.ccaa, count: cell.count });
      m.set(cell.empresa, list);
    }
    const result = new Map<string, string[]>();
    for (const [emp, list] of m) {
      result.set(
        emp,
        list
          .sort((a, b) => b.count - a.count)
          .slice(0, 3)
          .map((x) => x.ccaa),
      );
    }
    return result;
  }, [data]);

  // Top winners by count for Ganadores tab
  const topWinners = useMemo(() => {
    if (!data?.competitors?.length) return [];
    return [...data.competitors]
      .sort((a, b) => b.count - a.count)
      .slice(0, 15);
  }, [data]);

  // Top winners by importe
  const topWinnersByImporte = useMemo(() => {
    if (!data?.competitors?.length) return [];
    return [...data.competitors]
      .sort((a, b) => b.importe - a.importe)
      .slice(0, 15);
  }, [data]);

  // Filtered ganadores by keyword
  const filteredTopWinners = useMemo(() => {
    if (!ganadoresSearch) return topWinners;
    const q = ganadoresSearch.toLowerCase();
    return topWinners.filter((c) => c.nombre.toLowerCase().includes(q));
  }, [topWinners, ganadoresSearch]);

  const filteredTopWinnersByImporte = useMemo(() => {
    if (!ganadoresSearch) return topWinnersByImporte;
    const q = ganadoresSearch.toLowerCase();
    return topWinnersByImporte.filter((c) => c.nombre.toLowerCase().includes(q));
  }, [topWinnersByImporte, ganadoresSearch]);

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Ecosistema Partners
          </h1>
          <p className="text-muted-foreground">
            Grafo de co-adjudicacion entre empresas.
          </p>
        </div>
        <ExportPopover endpoint="/api/v1/exports/download" extraParams={{ seccion: "ecosistema-partners" }} />
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Total Empresas"
          value={isLoading ? undefined : formatNumber(data?.competitors.length)}
          icon={Users}
          loading={isLoading}
        />
        <KpiCard
          title="Total Adjudicaciones"
          value={
            isLoading ? undefined : formatNumber(data?.total_adjudicaciones)
          }
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
          icon={Network}
          loading={isLoading}
        />
        <KpiCard
          title="% PYME"
          value={isLoading ? undefined : formatPercent(data?.pct_pyme ?? 0)}
          icon={Users}
          loading={isLoading}
        />
      </div>

      {/* Tab Toggle */}
      <div className="flex items-center gap-1 rounded-lg border p-1 w-fit">
        <Button
          size="sm"
          variant={activeTab === "red" ? "default" : "ghost"}
          className="h-8 px-4 text-sm"
          onClick={() => setActiveTab("red")}
        >
          Red de Partners
        </Button>
        <Button
          size="sm"
          variant={activeTab === "ganadores" ? "default" : "ghost"}
          className="h-8 px-4 text-sm"
          onClick={() => setActiveTab("ganadores")}
        >
          Ganadores
        </Button>
      </div>

      {activeTab === "red" && (
      <>
      {/* Search */}
      <SearchAutocomplete
        className="max-w-md"
        placeholder="Buscar partners..."
        value={search}
        onChange={setSearch}
        suggestions={data?.competitors?.map((c) => c.nombre) ?? []}
        leftIcon={<Search className="h-4 w-4" />}
        inputClassName="pl-9"
      />

      {/* Search results cards */}
      {search && filteredPartners.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filteredPartners.slice(0, 6).map((c) => (
            <Card key={c.nombre} className="border-primary/20">
              <CardContent className="p-4 space-y-2">
                <p className="font-medium text-sm">
                  {truncate(c.nombre, 45)}
                </p>
                {c.nif && <p className="text-xs text-muted-foreground">NIF: {c.nif}</p>}
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  <span className="text-muted-foreground">Adjudicaciones</span>
                  <span className="tabular-nums font-medium">{formatNumber(c.count)}</span>
                  <span className="text-muted-foreground">Importe</span>
                  <span className="tabular-nums font-medium">{formatCurrency(c.importe)}</span>
                  <span className="text-muted-foreground">Cuota</span>
                  <span className="tabular-nums font-medium">{formatPercent(c.cuota)}</span>
                  {c.importe_medio != null && (
                    <>
                      <span className="text-muted-foreground">Imp. Medio</span>
                      <span className="tabular-nums font-medium">{formatCurrency(c.importe_medio)}</span>
                    </>
                  )}
                  {c.baja_media != null && (
                    <>
                      <span className="text-muted-foreground">Baja Media</span>
                      <span className="tabular-nums font-medium">{formatPercent(c.baja_media)}</span>
                    </>
                  )}
                </div>
                {empresaCcaaTop.get(c.nombre) && (
                  <div className="flex flex-wrap gap-1 pt-1">
                    {empresaCcaaTop.get(c.nombre)!.map((ccaa) => (
                      <Badge key={ccaa} variant="outline" className="text-xs">
                        {ccaa}
                      </Badge>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Force Graph */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Network className="h-4 w-4" />
              Red de Partners (Top {maxNodes})
            </CardTitle>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Max nodos</span>
                <input type="range" min={5} max={40} step={5} value={maxNodes} onChange={(e) => setMaxNodes(Number(e.target.value))} className="w-20 accent-primary" />
                <Badge variant="secondary" className="text-xs">{maxNodes}</Badge>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Min peso</span>
                <input type="range" min={1} max={10} step={1} value={minWeight} onChange={(e) => setMinWeight(Number(e.target.value))} className="w-20 accent-primary" />
                <Badge variant="secondary" className="text-xs">{minWeight}</Badge>
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[420px] w-full" />
          ) : graph.nodes.length > 0 ? (
            <ForceGraph
              nodes={graph.nodes}
              links={graph.links}
              height={420}
              className="min-h-[420px]"
            />
          ) : (
            <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-muted py-16">
              <Network className="h-16 w-16 text-muted-foreground/30 mb-4" />
              <p className="text-muted-foreground">
                Sin datos suficientes para construir el grafo
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Partners Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Partners por Importe</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : filteredPartners.length > 0 ? (
            <>
              <DataTable
                columns={partnerColumns}
                data={filteredPartners}
                initialSorting={[{ id: "importe", desc: true }]}
                emptyMessage="Sin partners disponibles"
                getRowClassName={(row) =>
                  cn(
                    search &&
                      row.original.nombre
                        .toLowerCase()
                        .includes(search.toLowerCase()) &&
                      "bg-primary/5",
                  )
                }
              />
              <Separator className="my-3" />
              <p className="text-xs text-muted-foreground">
                {filteredPartners.length} empresa
                {filteredPartners.length !== 1 ? "s" : ""}
              </p>
            </>
          ) : (
            <p className="py-8 text-center text-muted-foreground">
              Sin datos disponibles
            </p>
          )}
        </CardContent>
      </Card>
      </>
      )}

      {/* Ganadores Tab */}
      {activeTab === "ganadores" && (
      <>
      {/* Ganadores search */}
      <SearchAutocomplete
        className="max-w-md"
        placeholder="Buscar ganador..."
        value={ganadoresSearch}
        onChange={setGanadoresSearch}
        suggestions={data?.competitors?.map((c) => c.nombre) ?? []}
        leftIcon={<Search className="h-4 w-4" />}
        inputClassName="pl-9"
      />

      {/* KPI cards for winners */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Top Ganador (por Count)"
          value={isLoading ? undefined : truncate(topWinners[0]?.nombre ?? "-", 30)}
          icon={Trophy}
          loading={isLoading}
        />
        <KpiCard
          title="Top Ganador (por Importe)"
          value={isLoading ? undefined : truncate(topWinnersByImporte[0]?.nombre ?? "-", 30)}
          icon={TrendingUp}
          loading={isLoading}
        />
        <KpiCard
          title="Adjudicaciones Top 1"
          value={isLoading ? undefined : formatNumber(topWinners[0]?.count)}
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title="Importe Top 1"
          value={isLoading ? undefined : formatCurrency(topWinnersByImporte[0]?.importe)}
          icon={TrendingUp}
          loading={isLoading}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Bar: Top 15 by count */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Top 15 Ganadores (por Adjudicaciones)</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[450px] w-full" />
            ) : filteredTopWinners.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={Math.max(350, filteredTopWinners.length * 30)}>
                <BarChart
                  data={filteredTopWinners}
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
                    tickFormatter={(v: string) => truncate(v, 28)}
                  />
                  <Tooltip formatter={(v) => [formatNumber(v as number), "Adjudicaciones"]} />
                  <Bar dataKey="count" fill={CHART_SERIES[0]} radius={[0, 4, 4, 0]} name="Adjudicaciones" />
                </BarChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos disponibles</p>
            )}
          </CardContent>
        </Card>

        {/* Bar: Top 15 by importe */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Top 15 Ganadores (por Importe)</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[450px] w-full" />
            ) : filteredTopWinnersByImporte.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={Math.max(350, filteredTopWinnersByImporte.length * 30)}>
                <BarChart
                  data={filteredTopWinnersByImporte}
                  layout="vertical"
                  margin={{ left: 180 }}
                >
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis type="number" tick={{ fontSize: 12 }} tickFormatter={(v: number) => formatCurrency(v)} />
                  <YAxis
                    dataKey="nombre"
                    type="category"
                    tick={{ fontSize: 11 }}
                    width={170}
                    tickFormatter={(v: string) => truncate(v, 28)}
                  />
                  <Tooltip formatter={(v) => [formatCurrency(v as number), "Importe"]} />
                  <Bar dataKey="importe" fill={CHART_SERIES[1]} radius={[0, 4, 4, 0]} name="Importe" />
                </BarChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos disponibles</p>
            )}
          </CardContent>
        </Card>
      </div>
      </>
      )}
    </div>
  );
}
