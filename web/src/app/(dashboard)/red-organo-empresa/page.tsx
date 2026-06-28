"use client";
import { EmptyState } from "@/components/ui/empty-state";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
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
/*  Types — grafo de adjudicaciones REALES (backend)                  */
/* ------------------------------------------------------------------ */

interface GraphNode {
  name: string;
  type: "organo" | "empresa";
  degree: number;
  importe_total: number;
  key?: string | null;
}

interface GraphEdge {
  organo: string;
  empresa: string;
  contratos: number;
  importe_total: number;
  frecuencia_anual: number;
}

interface OrganCompanyGraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_organos: number;
  total_empresas: number;
}

/* ------------------------------------------------------------------ */
/*  Page                                                              */
/* ------------------------------------------------------------------ */

export default function RedOrganoEmpresaPage() {
  const router = useRouter();
  const [minContratos, setMinContratos] = useState(1);
  const [maxOrganos, setMaxOrganos] = useState(10);
  const [maxEmpresas, setMaxEmpresas] = useState(10);

  const { data, isLoading, error } = useFilteredQuery<OrganCompanyGraphResponse>(
    [
      "analytics",
      "organ-company-graph",
      String(minContratos),
      String(maxOrganos),
      String(maxEmpresas),
    ],
    "/api/v1/analytics/organ-company-graph",
    { staleTime: 5 * 60 * 1000 },
    {
      min_contratos: String(minContratos),
      top_organos: String(maxOrganos),
      top_empresas: String(maxEmpresas),
    },
  );

  const nodes = useMemo(() => data?.nodes ?? [], [data]);
  const edges = useMemo(() => data?.edges ?? [], [data]);

  // ForceGraph: nodos/aristas reales (peso = nº de contratos reales). El
  // componente escala el grosor de la arista; ya no se clampa en cliente.
  const { graphNodes, graphLinks } = useMemo(() => {
    const gNodes = nodes.map((n) => ({
      id: `${n.type}::${n.name}`,
      label: truncate(n.name, 28),
      group: n.type,
      size: Math.max(n.importe_total, 1),
      importe: n.importe_total,
      degree: n.degree,
      column: (n.type === "organo" ? 0 : 1) as 0 | 1,
    }));
    const gLinks = edges.map((e) => ({
      source: `organo::${e.organo}`,
      target: `empresa::${e.empresa}`,
      weight: e.contratos,
      importe: e.importe_total,
      contratos: e.contratos,
    }));
    return { graphNodes: gNodes, graphLinks: gLinks };
  }, [nodes, edges]);

  // Drill-down: nodo → ficha de órgano/empresa; arista → empresa adjudicataria.
  const navFromNodeId = (id: string) => {
    const sep = id.indexOf("::");
    const type = id.slice(0, sep);
    const name = id.slice(sep + 2);
    router.push(
      type === "organo"
        ? `/organos?q=${encodeURIComponent(name)}`
        : `/empresas?q=${encodeURIComponent(name)}`,
    );
  };

  // Aristas ordenadas para la tabla.
  const sortedEdges = useMemo(
    () => [...edges].sort((a, b) => b.contratos - a.contratos),
    [edges],
  );

  // Matriz órgano×empresa con CONTRATOS REALES (top-10 por importe).
  const matrix = useMemo(() => {
    const organos = nodes.filter((n) => n.type === "organo");
    const empresas = nodes.filter((n) => n.type === "empresa");
    const topOrg = [...organos].sort((a, b) => b.importe_total - a.importe_total).slice(0, 10);
    const topEmp = [...empresas].sort((a, b) => b.importe_total - a.importe_total).slice(0, 10);
    const cell = new Map<string, number>();
    for (const e of edges) cell.set(`${e.organo}|${e.empresa}`, e.contratos);
    const grid = topOrg.map((org) =>
      topEmp.map((emp) => cell.get(`${org.name}|${emp.name}`) ?? 0),
    );
    const maxCount = Math.max(1, ...grid.flat());
    return { topOrg, topEmp, grid, maxCount };
  }, [nodes, edges]);

  // KPIs
  const totalOrganos = data?.total_organos ?? 0;
  const totalEmpresas = data?.total_empresas ?? 0;
  const totalLinks = edges.length;
  const nOrgNodes = graphNodes.filter((n) => n.group === "organo").length;
  const nEmpNodes = graphNodes.filter((n) => n.group === "empresa").length;
  const possiblePairs = nOrgNodes * nEmpNodes;
  const densidad = possiblePairs > 0 ? (totalLinks / possiblePairs) * 100 : 0;

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
            Grafo bipartito de adjudicaciones reales: un enlace existe solo si el
            organo adjudico contratos a la empresa.
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
            <Skeleton className="h-[460px] w-full" />
          ) : graphNodes.length > 0 ? (
            <ForceGraph
              nodes={graphNodes}
              links={graphLinks}
              height={460}
              layout="bipartite"
              groupLabels={{ organo: "Órgano", empresa: "Empresa" }}
              onNodeClick={navFromNodeId}
              onLinkClick={(_source, target) => navFromNodeId(target)}
            />
          ) : (
            <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-muted py-16">
              <Network className="h-16 w-16 text-muted-foreground/30 mb-4" />
              <p className="text-muted-foreground">
                Sin adjudicaciones para los filtros actuales
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Matriz órgano-empresa (contratos reales) */}
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
          ) : matrix.topOrg.length === 0 || matrix.topEmp.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="overflow-x-auto">
              <div className="min-w-[700px]">
                {/* Column headers */}
                <div className="flex">
                  <div className="w-48 shrink-0" />
                  {matrix.topEmp.map((e, idx) => (
                    <div key={idx} className="flex-1 min-w-[60px] px-1 pb-2">
                      <div className="text-xs text-muted-foreground truncate -rotate-45 origin-bottom-left translate-x-4 w-20">
                        {truncate(e.name, 20)}
                      </div>
                    </div>
                  ))}
                </div>
                {/* Rows */}
                <div className="mt-8 space-y-1">
                  {matrix.grid.map((row, rowIdx) => (
                    <div key={rowIdx} className="flex items-center">
                      <div className="w-48 shrink-0 pr-2 text-xs text-muted-foreground truncate text-right">
                        {truncate(matrix.topOrg[rowIdx].name, 35)}
                      </div>
                      {row.map((val, colIdx) => (
                        <div
                          key={colIdx}
                          className="flex-1 min-w-[60px] px-0.5"
                          title={`${truncate(matrix.topOrg[rowIdx].name, 30)} — ${truncate(matrix.topEmp[colIdx].name, 30)}: ${val} contratos`}
                        >
                          <div
                            className="min-h-[44px] rounded-sm transition-colors flex items-center justify-center"
                            style={{
                              backgroundColor: `hsla(221, 83%, 53%, ${Math.max(0.05, val / matrix.maxCount)})`,
                            }}
                          >
                            {val > 0 && (
                              <span className="text-xs font-medium" style={{ color: val / matrix.maxCount > 0.4 ? "white" : "hsl(var(--foreground))" }}>
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
                        style={{ backgroundColor: `hsla(221, 83%, 53%, ${v})` }}
                      />
                    ))}
                  </div>
                  <span>Alta</span>
                  <span className="ml-2">
                    — N.º de adjudicaciones reales (organo → empresa)
                  </span>
                </div>
              </div>
            </div>
          )}
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
          ) : sortedEdges.length > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="text-left text-muted-foreground">
                    <TableHead>Organo</TableHead>
                    <TableHead>Empresa</TableHead>
                    <TableHead>Contratos</TableHead>
                    <TableHead>Importe total</TableHead>
                    <TableHead>Frec. anual</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedEdges.slice(0, 30).map((r, idx) => (
                    <TableRow key={idx}>
                      <TableCell>{truncate(r.organo, 40)}</TableCell>
                      <TableCell className="font-medium">{truncate(r.empresa, 35)}</TableCell>
                      <TableCell className="tabular-nums">{formatNumber(r.contratos)}</TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">
                        {formatCurrency(r.importe_total)}
                      </TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">
                        {r.frecuencia_anual.toFixed(1)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Separator className="my-3" />
              <p className="text-xs text-muted-foreground">
                {sortedEdges.length} relaciones de adjudicacion reales
              </p>
            </div>
          ) : (
            <p className="py-8 text-center text-muted-foreground">
              Sin relaciones para los filtros actuales
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
