"use client";
import { EmptyState } from "@/components/ui/empty-state";

import { useMemo, useState } from "react";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { KpiCard } from "@/components/charts/kpi-card";
import dynamic from "next/dynamic";
import { ExportPopover } from "@/components/export-popover";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const ForceGraph = dynamic(() => import("@/components/charts/force-graph").then(m => ({ default: m.ForceGraph })), { ssr: false, loading: () => <Skeleton className="h-[420px] w-full rounded-md" /> });
import {
  formatNumber,
  formatCurrency,
  truncate,
} from "@/lib/utils";
import { GitBranch, Building2, Users, Network } from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

interface Competitor {
  nombre: string;
  count: number;
  importe: number;
  cuota: number;
}

interface HeatmapCell {
  ccaa: string;
  empresa: string;
  count: number;
}

interface CompetitorsData {
  total_adjudicaciones: number;
  hhi: number;
  competitors: Competitor[];
  heatmap_ccaa: HeatmapCell[];
}

interface OrganoEntry {
  organo_contratacion: string;
  count: number;
  importe: number;
  pct: number;
  ccaa?: string | null;
}

interface OrganosData {
  total_organos: number;
  organos: OrganoEntry[];
  concentracion_top10: number;
}

/* ------------------------------------------------------------------ */
/*  Bipartite graph builder                                           */
/* ------------------------------------------------------------------ */

interface Relationship {
  organo: string;
  empresa: string;
  ccaa: string;
  count: number;
}

function buildBipartiteData(
  organos: OrganoEntry[],
  competitors: Competitor[],
  heatmap: HeatmapCell[],
) {
  const topOrganos = [...organos]
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);
  const topEmpresas = [...competitors]
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);

  const empresaNames = new Set(topEmpresas.map((e) => e.nombre));

  // Build organo→ccaa map
  const organoCcaa = new Map<string, string>();
  for (const o of topOrganos) {
    if (o.ccaa) organoCcaa.set(o.organo_contratacion, o.ccaa);
  }

  // Build empresa→ccaa map from heatmap
  const empresaCcaas = new Map<string, Set<string>>();
  for (const cell of heatmap) {
    if (!empresaNames.has(cell.empresa)) continue;
    const s = empresaCcaas.get(cell.empresa) ?? new Set();
    s.add(cell.ccaa);
    empresaCcaas.set(cell.empresa, s);
  }

  // Build relationships: organo↔empresa if they share CCAA
  const relationships: Relationship[] = [];
  const linkMap = new Map<string, number>();

  for (const organo of topOrganos) {
    const oCcaa = organoCcaa.get(organo.organo_contratacion);
    if (!oCcaa) continue;
    for (const empresa of topEmpresas) {
      const eCcaas = empresaCcaas.get(empresa.nombre);
      if (!eCcaas?.has(oCcaa)) continue;
      // Find count from heatmap
      const cell = heatmap.find(
        (h) => h.empresa === empresa.nombre && h.ccaa === oCcaa,
      );
      const count = cell?.count ?? 1;
      const key = `${organo.organo_contratacion}::${empresa.nombre}`;
      linkMap.set(key, (linkMap.get(key) ?? 0) + count);
      relationships.push({
        organo: organo.organo_contratacion,
        empresa: empresa.nombre,
        ccaa: oCcaa,
        count,
      });
    }
  }

  // Nodes
  const nodes = [
    ...topOrganos.map((o) => ({
      id: `org::${o.organo_contratacion}`,
      label: truncate(o.organo_contratacion, 28),
      group: "organo",
      size: o.count * 100,
    })),
    ...topEmpresas.map((e) => ({
      id: `emp::${e.nombre}`,
      label: truncate(e.nombre, 28),
      group: "empresa",
      size: e.importe,
    })),
  ];

  // Links
  const links: { source: string; target: string; weight: number }[] = [];
  for (const [key, weight] of linkMap) {
    const [organo, empresa] = key.split("::");
    links.push({
      source: `org::${organo}`,
      target: `emp::${empresa}`,
      weight: Math.min(weight, 8),
    });
  }

  // Sorted relationships table
  const sortedRels = [...relationships].sort((a, b) => b.count - a.count);

  return { nodes, links, relationships: sortedRels };
}

/* ------------------------------------------------------------------ */
/*  Page                                                              */
/* ------------------------------------------------------------------ */

export default function RedOrganoEmpresaPage() {
  const [minContratos, setMinContratos] = useState(1);
  const [maxOrganos, setMaxOrganos] = useState(10);
  const [maxEmpresas, setMaxEmpresas] = useState(10);

  const {
    data: competitorsData,
    isLoading: loadingComp,
    error: errorComp,
  } = useFilteredQuery<CompetitorsData>(
    ["analytics", "competitors"],
    "/api/v1/analytics/competitors",
    { staleTime: 5 * 60 * 1000 },
  );

  const {
    data: organosData,
    isLoading: loadingOrg,
    error: errorOrg,
  } = useFilteredQuery<OrganosData>(
    ["analytics", "organos"],
    "/api/v1/analytics/organos",
    { staleTime: 5 * 60 * 1000 },
  );

  const isLoading = loadingComp || loadingOrg;
  const error = errorComp || errorOrg;

  const { nodes, links, relationships } = useMemo(() => {
    if (!competitorsData || !organosData)
      return { nodes: [], links: [], relationships: [] };
    // Pass only top N organos/empresas based on sliders
    const slicedOrganos = [...organosData.organos].sort((a, b) => b.count - a.count).slice(0, maxOrganos);
    const slicedCompetitors = [...competitorsData.competitors].sort((a, b) => b.count - a.count).slice(0, maxEmpresas);
    const result = buildBipartiteData(
      slicedOrganos,
      slicedCompetitors,
      competitorsData.heatmap_ccaa,
    );
    // Filter links by minContratos
    const filteredLinks = result.links.filter((l) => l.weight >= minContratos);
    const filteredRels = result.relationships.filter((r) => r.count >= minContratos);
    return { nodes: result.nodes, links: filteredLinks, relationships: filteredRels };
  }, [competitorsData, organosData, maxOrganos, maxEmpresas, minContratos]);

  // KPIs
  const totalOrganos = organosData?.total_organos ?? 0;
  const totalEmpresas = competitorsData?.competitors.length ?? 0;
  const totalLinks = links.length;
  const possiblePairs = Math.min(
    (organosData?.organos.length ?? 0),
    10,
  ) * Math.min((competitorsData?.competitors.length ?? 0), 10);
  const densidad =
    possiblePairs > 0 ? (totalLinks / possiblePairs) * 100 : 0;

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
            Red Organo-Empresa
          </h1>
          <p className="text-muted-foreground">
            Grafo bipartito entre organos de contratacion y empresas.
          </p>
        </div>
        <ExportPopover endpoint="/api/v1/exports/download" extraParams={{ seccion: "red-organo-empresa" }} />
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Organos Unicos"
          value={isLoading ? undefined : formatNumber(totalOrganos)}
          icon={Building2}
          loading={isLoading}
        />
        <KpiCard
          title="Empresas Unicas"
          value={isLoading ? undefined : formatNumber(totalEmpresas)}
          icon={Users}
          loading={isLoading}
        />
        <KpiCard
          title="Relaciones (links)"
          value={isLoading ? undefined : formatNumber(totalLinks)}
          icon={GitBranch}
          loading={isLoading}
        />
        <KpiCard
          title="Densidad"
          value={isLoading ? undefined : `${densidad.toFixed(1)}%`}
          subtitle="Relaciones / pares posibles"
          icon={Network}
          loading={isLoading}
        />
      </div>

      {/* Bipartite Force Graph */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Network className="h-4 w-4" />
              Grafo Bipartito (Top {maxOrganos} Organos x Top {maxEmpresas} Empresas)
            </CardTitle>
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Organos</span>
                <input type="range" aria-label="Max organos" min={3} max={20} step={1} value={maxOrganos} onChange={(e) => setMaxOrganos(Number(e.target.value))} className="w-20 accent-primary" />
                <Badge variant="secondary" className="text-xs">{maxOrganos}</Badge>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Empresas</span>
                <input type="range" aria-label="Max empresas" min={3} max={20} step={1} value={maxEmpresas} onChange={(e) => setMaxEmpresas(Number(e.target.value))} className="w-20 accent-primary" />
                <Badge variant="secondary" className="text-xs">{maxEmpresas}</Badge>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Min contratos</span>
                <input type="range" aria-label="Min contratos" min={1} max={20} step={1} value={minContratos} onChange={(e) => setMinContratos(Number(e.target.value))} className="w-20 accent-primary" />
                <Badge variant="secondary" className="text-xs">{minContratos}</Badge>
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[420px] w-full" />
          ) : nodes.length > 0 ? (
            <>
              <div className="mb-3 flex gap-4 text-xs text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <span className="inline-block h-3 w-3 rounded-full bg-[#4e79a7]" />
                  Organo
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block h-3 w-3 rounded-full bg-[#e15759]" />
                  Empresa
                </span>
              </div>
              <ForceGraph
                nodes={nodes}
                links={links}
                height={420}
                className="min-h-[420px]"
              />
            </>
          ) : (
            <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-muted py-16">
              <Network className="h-16 w-16 text-muted-foreground/30 mb-4" />
              <p className="text-muted-foreground">
                Sin datos de relaciones disponibles
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Heatmap matrix */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <GitBranch className="h-4 w-4" />
            Matriz Organo-Empresa (Top 10 x Top 10)
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : (() => {
            const topOrg = [...(organosData?.organos ?? [])]
              .sort((a, b) => b.count - a.count)
              .slice(0, 10);
            const topEmp = [...(competitorsData?.competitors ?? [])]
              .sort((a, b) => b.count - a.count)
              .slice(0, 10);
            if (topOrg.length === 0 || topEmp.length === 0)
              return (
                <EmptyState />
              );

            // Build lookup: organo→ccaa, empresa→ccaa→count
            const organoCcaaMap = new Map<string, string>();
            for (const o of topOrg)
              if (o.ccaa) organoCcaaMap.set(o.organo_contratacion, o.ccaa);

            const empCcaaCount = new Map<string, Map<string, number>>();
            for (const cell of competitorsData?.heatmap_ccaa ?? []) {
              let m = empCcaaCount.get(cell.empresa);
              if (!m) {
                m = new Map();
                empCcaaCount.set(cell.empresa, m);
              }
              m.set(cell.ccaa, (m.get(cell.ccaa) ?? 0) + cell.count);
            }

            let maxCount = 1;
            const matrix: number[][] = topOrg.map((org) => {
              const ccaa = organoCcaaMap.get(org.organo_contratacion);
              return topEmp.map((emp) => {
                if (!ccaa) return 0;
                const cnt = empCcaaCount.get(emp.nombre)?.get(ccaa) ?? 0;
                if (cnt > maxCount) maxCount = cnt;
                return cnt;
              });
            });

            return (
              <div className="overflow-x-auto">
                <div className="min-w-[700px]">
                  {/* Column headers */}
                  <div className="flex">
                    <div className="w-48 shrink-0" />
                    {topEmp.map((e, idx) => (
                      <div
                        key={idx}
                        className="flex-1 min-w-[60px] px-1 pb-2"
                      >
                        <div className="text-xs text-muted-foreground truncate -rotate-45 origin-bottom-left translate-x-4 w-20">
                          {truncate(e.nombre, 20)}
                        </div>
                      </div>
                    ))}
                  </div>
                  {/* Rows */}
                  <div className="mt-8 space-y-1">
                    {matrix.map((row, rowIdx) => (
                      <div key={rowIdx} className="flex items-center">
                        <div className="w-48 shrink-0 pr-2 text-xs text-muted-foreground truncate text-right">
                          {truncate(topOrg[rowIdx].organo_contratacion, 35)}
                        </div>
                        {row.map((val, colIdx) => (
                           <div
                         key={colIdx}
                         className="flex-1 min-w-[60px] px-0.5"
                         title={`${truncate(topOrg[rowIdx].organo_contratacion, 30)} — ${truncate(topEmp[colIdx].nombre, 30)}: ${val}`}
                       >
                            <div
                              className="min-h-[44px] rounded-sm transition-colors flex items-center justify-center"
                              style={{
                                backgroundColor: `hsla(221, 83%, 53%, ${Math.max(0.05, val / maxCount)})`,
                              }}
                            >
                              {val > 0 && (
                                <span className="text-xs font-medium" style={{ color: val / maxCount > 0.4 ? "white" : "hsl(var(--foreground))" }}>
                                  {val}
                                </span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                  {/* Legend */}
                  <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
                    <span>Baja</span>
                    <div className="flex gap-0.5">
                      {[0.05, 0.15, 0.3, 0.5, 0.7, 0.9].map((v) => (
                        <div
                          key={v}
                          className="h-4 w-6 rounded-sm"
                          style={{
                            backgroundColor: `hsla(221, 83%, 53%, ${v})`,
                          }}
                        />
                      ))}
                    </div>
                    <span>Alta</span>
                    <span className="ml-2">
                      — Actividad en misma CCAA (estimada por co-ocurrencia geográfica)
                    </span>
                  </div>
                </div>
              </div>
            );
          })()}
        </CardContent>
      </Card>

      {/* Relationships Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Relaciones Organo-Empresa
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : relationships.length > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="text-left text-muted-foreground">
                    <TableHead>Organo</TableHead>
                    <TableHead>Empresa</TableHead>
                    <TableHead>CCAA</TableHead>
                    <TableHead>Contratos</TableHead>
                    <TableHead>Importe Est.</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {relationships.slice(0, 30).map((r, idx) => {
                    // Estimate importe from competitor average
                    const comp = competitorsData?.competitors.find((c) => c.nombre === r.empresa);
                    const impMedio = comp && comp.count > 0 ? comp.importe / comp.count : 0;
                    return (
                    <TableRow key={idx}>
                      <TableCell>
                        {truncate(r.organo, 40)}
                      </TableCell>
                      <TableCell className="font-medium">
                        {truncate(r.empresa, 35)}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{r.ccaa}</Badge>
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {formatNumber(r.count)}
                      </TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">
                        {impMedio > 0 ? formatCurrency(impMedio * r.count) : "-"}
                      </TableCell>
                    </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              <Separator className="my-3" />
              <p className="text-xs text-muted-foreground">
                {relationships.length} relaciones detectadas
              </p>
            </div>
          ) : (
            <p className="py-8 text-center text-muted-foreground">
              Sin relaciones detectadas
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
