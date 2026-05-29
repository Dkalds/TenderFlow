"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { formatNumber, truncate } from "@/lib/utils";
import { GitBranch, Building2, Users, Info } from "lucide-react";

interface Competitor {
  nombre: string;
  count: number;
  importe: number;
  cuota: number;
}

interface CompetitorsData {
  total_adjudicaciones: number;
  competitors: Competitor[];
}

interface OrganoItem {
  organo_contratacion: string;
  n: number;
  importe_total?: number;
}

interface OrganosData {
  total_organos: number;
  organos: OrganoItem[];
}

async function fetchCompetitors(): Promise<CompetitorsData> {
  const res = await fetch("/api/v1/analytics/competitors", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Error al cargar datos de competidores");
  return res.json();
}

async function fetchOrganos(): Promise<OrganosData> {
  const res = await fetch("/api/v1/analytics/organos", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Error al cargar datos de organos");
  return res.json();
}

export default function RedOrganoEmpresaPage() {
  const {
    data: competitorsData,
    isLoading: loadingComp,
    error: errorComp,
  } = useQuery({
    queryKey: ["analytics", "competitors"],
    queryFn: fetchCompetitors,
    staleTime: 5 * 60 * 1000,
  });

  const {
    data: organosData,
    isLoading: loadingOrg,
    error: errorOrg,
  } = useQuery({
    queryKey: ["analytics", "organos"],
    queryFn: fetchOrganos,
    staleTime: 5 * 60 * 1000,
  });

  const isLoading = loadingComp || loadingOrg;
  const error = errorComp || errorOrg;

  const topOrganos = useMemo(() => {
    if (!organosData?.organos) return [];
    return [...organosData.organos].sort((a, b) => b.n - a.n).slice(0, 10);
  }, [organosData]);

  const topEmpresas = useMemo(() => {
    if (!competitorsData?.competitors) return [];
    return [...competitorsData.competitors].sort((a, b) => b.count - a.count).slice(0, 10);
  }, [competitorsData]);

  // Simulate a heatmap matrix — in reality this would need cross-reference data
  // For now, generate intensity based on relative sizes
  const matrix = useMemo(() => {
    if (topOrganos.length === 0 || topEmpresas.length === 0) return [];
    const maxOrgN = Math.max(...topOrganos.map((o) => o.n));
    const maxEmpN = Math.max(...topEmpresas.map((e) => e.count));
    return topOrganos.map((organo) => ({
      organo: organo.organo_contratacion,
      cells: topEmpresas.map((empresa) => {
        // Heuristic: likelihood of relationship based on relative activity
        const intensity = Math.min(1, ((organo.n / maxOrgN) * (empresa.count / maxEmpN)) * 3);
        return {
          empresa: empresa.nombre,
          intensity,
        };
      }),
    }));
  }, [topOrganos, topEmpresas]);

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Red Organo-Empresa</h1>
        <p className="text-muted-foreground">
          Grafo bipartito entre organos de contratacion y empresas.
        </p>
      </div>

      {/* Info Banner */}
      <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950/30">
        <Info className="mt-0.5 h-5 w-5 shrink-0 text-blue-600 dark:text-blue-400" />
        <div className="text-sm text-blue-800 dark:text-blue-300">
          <p className="font-medium">Grafo bipartito organo-empresa</p>
          <p className="mt-1 text-blue-700/80 dark:text-blue-400/80">
            Esta vista muestra la relacion entre organos contratantes y empresas adjudicatarias.
            La matriz de calor indica la intensidad estimada de las relaciones. Los datos de
            co-ocurrencia exactos se integraran en futuras versiones.
          </p>
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          title="Organos Contratantes"
          value={isLoading ? undefined : formatNumber(organosData?.total_organos)}
          icon={Building2}
          loading={isLoading}
        />
        <KpiCard
          title="Empresas Adjudicatarias"
          value={isLoading ? undefined : formatNumber(competitorsData?.competitors.length)}
          icon={Users}
          loading={isLoading}
        />
        <KpiCard
          title="Total Adjudicaciones"
          value={isLoading ? undefined : formatNumber(competitorsData?.total_adjudicaciones)}
          icon={GitBranch}
          loading={isLoading}
        />
      </div>

      {/* Heatmap Matrix */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <GitBranch className="h-4 w-4" />
            Matriz Organo-Empresa (Top 10 x Top 10)
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[500px] w-full" />
          ) : matrix.length > 0 ? (
            <div className="overflow-x-auto">
              <div className="min-w-[700px]">
                {/* Column headers */}
                <div className="flex">
                  <div className="w-48 shrink-0" />
                  {topEmpresas.map((e, idx) => (
                    <div
                      key={idx}
                      className="flex-1 min-w-[60px] px-1 pb-2"
                    >
                      <div className="text-[10px] text-muted-foreground truncate -rotate-45 origin-bottom-left translate-x-4 w-20">
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
                        {truncate(row.organo, 35)}
                      </div>
                      {row.cells.map((cell, colIdx) => (
                        <div
                          key={colIdx}
                          className="flex-1 min-w-[60px] px-0.5"
                          title={`${truncate(row.organo, 30)} — ${truncate(cell.empresa, 30)}`}
                        >
                          <div
                            className="h-8 rounded-sm transition-colors"
                            style={{
                              backgroundColor:
                                cell.intensity > 0.5
                                  ? `hsla(221, 83%, 53%, ${cell.intensity})`
                                  : cell.intensity > 0.2
                                    ? `hsla(221, 83%, 53%, ${cell.intensity})`
                                    : `hsla(221, 83%, 53%, ${Math.max(0.05, cell.intensity)})`,
                            }}
                          />
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
                  <span className="ml-2">— Intensidad estimada de relacion</span>
                </div>
              </div>
            </div>
          ) : (
            <p className="py-12 text-center text-muted-foreground">Sin datos disponibles</p>
          )}
        </CardContent>
      </Card>

      {/* Cross-reference: Top organos and their top companies */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Principales Organos y sus Adjudicatarios</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : topOrganos.length > 0 ? (
            <div className="space-y-4">
              {topOrganos.slice(0, 5).map((organo, idx) => (
                <div key={idx} className="rounded-lg border p-4">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-medium">{truncate(organo.organo_contratacion, 60)}</h4>
                    <Badge variant="secondary" className="tabular-nums">
                      {formatNumber(organo.n)} adj.
                    </Badge>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {topEmpresas.slice(0, 5).map((emp, eIdx) => (
                      <Badge key={eIdx} variant="outline" className="text-xs">
                        {truncate(emp.nombre, 25)}
                      </Badge>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-8 text-center text-muted-foreground">Sin datos disponibles</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
