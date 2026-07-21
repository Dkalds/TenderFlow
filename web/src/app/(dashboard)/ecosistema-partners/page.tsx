"use client";
import { EmptyState } from "@/components/ui/empty-state";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { KpiCard } from "@/components/charts/kpi-card";
import dynamic from "next/dynamic";
import { ExportPopover } from "@/components/export-popover";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { DataTable } from "@/components/ui/data-table";
import { type ColumnDef } from "@tanstack/react-table";

const ForceGraph = dynamic(() => import("@/components/charts/force-graph").then(m => ({ default: m.ForceGraph })), { ssr: false, loading: () => <Skeleton className="h-[420px] w-full rounded-md" /> });
const GanadoresCountBarChart = dynamic(() => import("@/components/charts/ecosistema-partners-charts").then(m => ({ default: m.GanadoresCountBarChart })), { ssr: false, loading: () => <Skeleton className="h-[450px] w-full rounded-md" /> });
const GanadoresImporteBarChart = dynamic(() => import("@/components/charts/ecosistema-partners-charts").then(m => ({ default: m.GanadoresImporteBarChart })), { ssr: false, loading: () => <Skeleton className="h-[450px] w-full rounded-md" /> });
import {
  formatCurrency,
  formatNumber,
  formatPercent,
  truncate,
  cn,
} from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Network, Hash, Users, Search, Trophy, TrendingUp, Layers, ArrowUpRight } from "lucide-react";

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
/*  Types — grafo de co-licitación REAL (UTE)                         */
/* ------------------------------------------------------------------ */

interface PartnerNode {
  name: string;
  contratos: number;
  importe: number;
  community?: number | null;
}

interface PartnerEdge {
  source: string;
  target: string;
  contratos: number;
  importe: number;
}

interface CommunitySummary {
  community: number;
  size: number;
  leader: string;
  importe_total: number;
  top_members: string[];
}

interface PartnershipGraphResponse {
  nodes: PartnerNode[];
  edges: PartnerEdge[];
  communities: CommunitySummary[];
  total_utes: number;
}

/* ------------------------------------------------------------------ */
/*  Page                                                              */
/* ------------------------------------------------------------------ */

export default function EcosistemaPartnersPage() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [ganadoresSearch, setGanadoresSearch] = useState("");
  const [activeTab, setActiveTab] = useState<"red" | "ganadores">("red");
  const [minWeight, setMinWeight] = useState(1);
  const [maxNodes, setMaxNodes] = useState(20);
  // Partner enfocado: cuando está activo, el grafo muestra su ego-network en vez
  // del hairball global.
  const [focusPartner, setFocusPartner] = useState<string | null>(null);
  const { data, isLoading, error } = useFilteredQuery<CompetitorsData>(
    ["analytics", "competitors"],
    "/api/v1/analytics/competitors",
    { staleTime: 5 * 60 * 1000 },
  );

  // Grafo de co-licitación REAL (UTE), acotado en backend por los sliders.
  const { data: graphData, isLoading: graphLoading } =
    useFilteredQuery<PartnershipGraphResponse>(
      ["analytics", "partnership-graph", String(maxNodes), String(minWeight)],
      "/api/v1/analytics/partnership-graph",
      { staleTime: 5 * 60 * 1000 },
      { top_nodes: String(maxNodes), min_contratos: String(minWeight) },
    );

  const communities = useMemo(() => graphData?.communities ?? [], [graphData]);

  const { graphNodes, graphLinks, graphGroupLabels, graphHighlightIds } = useMemo(() => {
    const lowHL = search.trim().toLowerCase();
    const gNodes = (graphData?.nodes ?? []).map((n) => ({
      id: n.name,
      label: truncate(n.name, 30),
      // Color por comunidad (clúster de co-licitación) si el backend la calculó.
      group: n.community != null ? `c${n.community}` : "empresa",
      size: Math.max(n.importe, 1),
      importe: n.importe,
      contratos: n.contratos,
    }));
    const gLinks = (graphData?.edges ?? []).map((e) => ({
      source: e.source,
      target: e.target,
      weight: e.contratos,
      importe: e.importe,
      contratos: e.contratos,
    }));
    const comms = Array.from(new Set(gNodes.map((n) => n.group))).sort();
    const labels: Record<string, string> = {};
    for (const g of comms) {
      labels[g] = g === "empresa" ? "Empresa" : `Clúster ${Number(g.slice(1)) + 1}`;
    }
    const hl = lowHL
      ? gNodes.filter((n) => n.id.toLowerCase().includes(lowHL)).map((n) => n.id)
      : [];
    return {
      graphNodes: gNodes,
      graphLinks: gLinks,
      graphGroupLabels: labels,
      graphHighlightIds: hl,
    };
  }, [graphData, search]);

  // Ego-network del partner enfocado: subconjunto (vecinos directos) del grafo
  // que YA vino del backend. Es un enfoque de vista, no fabricación de datos.
  const { egoNodes, egoLinks } = useMemo(() => {
    if (!focusPartner) return { egoNodes: [], egoLinks: [] };
    const neighbors = new Set<string>([focusPartner]);
    for (const l of graphLinks) {
      if (l.source === focusPartner) neighbors.add(l.target);
      if (l.target === focusPartner) neighbors.add(l.source);
    }
    return {
      egoNodes: graphNodes.filter((n) => neighbors.has(n.id)),
      egoLinks: graphLinks.filter((l) => neighbors.has(l.source) && neighbors.has(l.target)),
    };
  }, [focusPartner, graphNodes, graphLinks]);

  const partnerNames = useMemo(
    () => (graphData?.nodes ?? []).map((n) => n.name),
    [graphData],
  );

  const focusOnPartner = (name: string) => {
    if (partnerNames.includes(name)) setFocusPartner(name);
  };

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
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
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
            Clústeres de empresas que co-licitan en UTE y con quién conviene aliarse
            por segmento.
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
          title="Comunidades"
          value={graphLoading ? undefined : formatNumber(communities.length)}
          subtitle="Clústeres de co-licitación"
          icon={Layers}
          loading={graphLoading}
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
          Partners &amp; Comunidades
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
      {/* HERO: comunidades de co-licitación */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Layers className="h-4 w-4" />
            Comunidades de co-licitación
          </CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            Bloques de empresas que forman UTEs entre sí. Click en una para enfocar su red.
          </p>
        </CardHeader>
        <CardContent>
          {graphLoading ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-32 w-full rounded-md" />
              ))}
            </div>
          ) : communities.length > 0 ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {communities.map((c) => (
                <Card key={c.community} className="border-primary/15">
                  <CardContent className="space-y-2 p-4">
                    <div className="flex items-center justify-between">
                      <Badge variant="secondary" className="text-xs">
                        Clúster {c.community + 1}
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        {formatNumber(c.size)} empresas
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => focusOnPartner(c.leader)}
                      className="block text-left text-sm font-medium hover:text-primary"
                    >
                      {truncate(c.leader, 40)}
                    </button>
                    <p className="text-xs tabular-nums text-muted-foreground">
                      {formatCurrency(c.importe_total)} en co-licitaciones
                    </p>
                    <div className="flex flex-wrap gap-1 pt-1">
                      {c.top_members
                        .filter((m) => m !== c.leader)
                        .slice(0, 3)
                        .map((m) => (
                          <button
                            key={m}
                            type="button"
                            onClick={() => focusOnPartner(m)}
                            className="rounded border px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-muted"
                          >
                            {truncate(m, 24)}
                          </button>
                        ))}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={Layers}
              title="Sin comunidades"
              hint="No hay suficientes UTEs conectadas para detectar clústeres con los filtros actuales."
            />
          )}
        </CardContent>
      </Card>

      {/* Search */}
      <SearchAutocomplete
        className="max-w-md"
        placeholder="Buscar partner y enfocar su red..."
        value={search}
        onChange={setSearch}
        onSubmit={focusOnPartner}
        suggestions={partnerNames}
        leftIcon={<Search className="h-4 w-4" />}
        inputClassName="pl-9"
      />

      {/* Force Graph: ego del partner enfocado o red global */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Network className="h-4 w-4" />
              {focusPartner ? (
                <>
                  Red de {truncate(focusPartner, 34)}
                </>
              ) : (
                <>Red de Partners (Top {maxNodes})</>
              )}
            </CardTitle>
            <div className="flex items-center gap-4">
              {focusPartner ? (
                <button
                  type="button"
                  onClick={() => setFocusPartner(null)}
                  className="rounded border px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted"
                >
                  Ver toda la red
                </button>
              ) : (
                <>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">Max nodos</span>
                    <input type="range" aria-label="Max nodos" min={5} max={40} step={5} value={maxNodes} onChange={(e) => setMaxNodes(Number(e.target.value))} className="w-20 accent-primary" />
                    <Badge variant="secondary" className="text-xs">{maxNodes}</Badge>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">Min peso</span>
                    <input type="range" aria-label="Min peso" min={1} max={10} step={1} value={minWeight} onChange={(e) => setMinWeight(Number(e.target.value))} className="w-20 accent-primary" />
                    <Badge variant="secondary" className="text-xs">{minWeight}</Badge>
                  </div>
                </>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {graphLoading ? (
            <Skeleton className="h-[460px] w-full" />
          ) : focusPartner ? (
            egoNodes.length > 0 ? (
              <ForceGraph
                nodes={egoNodes}
                links={egoLinks}
                height={460}
                layout="ego"
                centerId={focusPartner}
                groupLabels={graphGroupLabels}
                onNodeClick={(id) =>
                  id === focusPartner
                    ? router.push(`/empresas?q=${encodeURIComponent(id)}`)
                    : setFocusPartner(id)
                }
              />
            ) : (
              <EmptyState
                icon={Network}
                title="Sin co-licitaciones"
                hint="Este partner no tiene UTEs conjuntas en el grafo actual."
              />
            )
          ) : graphNodes.length > 0 ? (
            <ForceGraph
              nodes={graphNodes}
              links={graphLinks}
              height={460}
              layout="force"
              groupLabels={graphGroupLabels}
              highlightIds={graphHighlightIds}
              onNodeClick={(id) => setFocusPartner(id)}
            />
          ) : (
            <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-muted py-16">
              <Network className="h-16 w-16 text-muted-foreground/30 mb-4" />
              <p className="text-muted-foreground">
                Sin co-licitaciones (UTE) para los filtros actuales
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Search results cards */}
      {search && filteredPartners.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filteredPartners.slice(0, 6).map((c) => (
            <Card key={c.nombre} className="border-primary/20">
              <CardContent className="p-4 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <p className="font-medium text-sm">{truncate(c.nombre, 40)}</p>
                  <button
                    type="button"
                    onClick={() => focusOnPartner(c.nombre)}
                    className="mt-0.5 shrink-0 text-muted-foreground hover:text-primary"
                    aria-label="Enfocar red de este partner"
                  >
                    <ArrowUpRight className="h-4 w-4" />
                  </button>
                </div>
                {c.nif && <p className="text-xs text-muted-foreground">NIF: {c.nif}</p>}
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  <span className="text-muted-foreground">Adjudicaciones</span>
                  <span className="tabular-nums font-medium">{formatNumber(c.count)}</span>
                  <span className="text-muted-foreground">Importe</span>
                  <span className="tabular-nums font-medium">{formatCurrency(c.importe)}</span>
                  <span className="text-muted-foreground">Cuota</span>
                  <span className="tabular-nums font-medium">{formatPercent(c.cuota)}</span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

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
              <GanadoresCountBarChart data={filteredTopWinners} />
            ) : (
              <EmptyState />
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
              <GanadoresImporteBarChart data={filteredTopWinnersByImporte} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>
      </>
      )}
    </div>
  );
}
