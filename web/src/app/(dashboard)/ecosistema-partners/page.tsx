"use client";

import { useQuery } from "@tanstack/react-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { formatCurrency, formatNumber, formatPercent, truncate } from "@/lib/utils";
import { Network, Hash, Info, Users } from "lucide-react";

interface Competitor {
  nombre: string;
  count: number;
  importe: number;
  cuota: number;
}

interface CompetitorsData {
  total_adjudicaciones: number;
  hhi: number;
  competitors: Competitor[];
}

async function fetchCompetitors(): Promise<CompetitorsData> {
  const res = await fetch("/api/v1/analytics/competitors", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Error al cargar datos de partners");
  return res.json();
}

export default function EcosistemaPartnersPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["analytics", "competitors"],
    queryFn: fetchCompetitors,
    staleTime: 5 * 60 * 1000,
  });

  const topPartners = data?.competitors
    ? [...data.competitors].sort((a, b) => b.importe - a.importe).slice(0, 20)
    : [];

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
        <h1 className="text-2xl font-bold tracking-tight">Ecosistema Partners</h1>
        <p className="text-muted-foreground">
          Grafo de co-adjudicacion entre empresas.
        </p>
      </div>

      {/* Graph Placeholder */}
      <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950/30">
        <Info className="mt-0.5 h-5 w-5 shrink-0 text-blue-600 dark:text-blue-400" />
        <div className="text-sm text-blue-800 dark:text-blue-300">
          <p className="font-medium">Grafo de co-adjudicaciones</p>
          <p className="mt-1 text-blue-700/80 dark:text-blue-400/80">
            La visualizacion del grafo de red se implementara con una libreria especializada
            (e.g., react-force-graph). Requiere datos de consorcios y co-adjudicaciones para
            mapear las relaciones entre partners.
          </p>
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          title="Total Empresas"
          value={isLoading ? undefined : formatNumber(data?.competitors.length)}
          icon={Users}
          loading={isLoading}
        />
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
          icon={Network}
          loading={isLoading}
        />
      </div>

      {/* Graph Placeholder Visual */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Network className="h-4 w-4" />
            Red de Partners
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[300px] w-full" />
          ) : (
            <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-muted py-16">
              <Network className="h-16 w-16 text-muted-foreground/30 mb-4" />
              <p className="text-lg font-medium text-muted-foreground">
                Visualizacion de grafo de red
              </p>
              <p className="text-sm text-muted-foreground/70 mt-1 max-w-md text-center">
                El grafo interactivo force-directed mostrara las conexiones entre empresas
                que co-participan en licitaciones. Proximamente disponible.
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Top Partners Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Top Partners por Importe</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : topPartners.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="px-3 py-2 font-medium">#</th>
                    <th className="px-3 py-2 font-medium">Empresa</th>
                    <th className="px-3 py-2 font-medium">Adjudicaciones</th>
                    <th className="px-3 py-2 font-medium">Importe</th>
                    <th className="px-3 py-2 font-medium">Cuota</th>
                  </tr>
                </thead>
                <tbody>
                  {topPartners.map((c, idx) => (
                    <tr key={idx} className="border-b last:border-0 hover:bg-muted/50">
                      <td className="px-3 py-2 text-muted-foreground">{idx + 1}</td>
                      <td className="px-3 py-2 font-medium">{truncate(c.nombre, 50)}</td>
                      <td className="px-3 py-2 tabular-nums">{formatNumber(c.count)}</td>
                      <td className="px-3 py-2 tabular-nums">{formatCurrency(c.importe)}</td>
                      <td className="px-3 py-2 tabular-nums">
                        <Badge variant="secondary">{formatPercent(c.cuota)}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Separator className="my-3" />
              <p className="text-xs text-muted-foreground">
                Mostrando top {topPartners.length} empresas por importe adjudicado
              </p>
            </div>
          ) : (
            <p className="py-8 text-center text-muted-foreground">Sin datos disponibles</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
