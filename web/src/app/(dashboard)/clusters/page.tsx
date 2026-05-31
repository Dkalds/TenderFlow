"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { type ColumnDef } from "@tanstack/react-table";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { formatNumber } from "@/lib/utils";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";
import { Waypoints, Hash, Sparkles, FlaskConical } from "lucide-react";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  ZAxis,
} from "recharts";

interface OverviewResponse {
  total_licitaciones: number;
  por_cpv: { cpv: string; descripcion?: string; n: number }[];
}

async function fetchOverview(): Promise<OverviewResponse> {
  const res = await fetch("/api/v1/analytics/overview", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to fetch overview");
  return res.json();
}



/** Generate deterministic pseudo-random scatter points to simulate a UMAP projection */
function generateMockScatter(
  cpvs: { cpv: string; descripcion?: string; n: number }[],
) {
  const points: { x: number; y: number; z: number; cluster: string }[] = [];
  const top = cpvs.slice(0, 8);

  top.forEach((cpv, clusterIdx) => {
    // Seed center from cpv string hash
    const hash = cpv.cpv
      .split("")
      .reduce((acc, c) => acc + c.charCodeAt(0), 0);
    const cx = ((hash * 7) % 80) + 10;
    const cy = ((hash * 13) % 80) + 10;
    const numPoints = Math.min(cpv.n, 30);

    for (let i = 0; i < numPoints; i++) {
      const angle = ((hash + i * 137) % 360) * (Math.PI / 180);
      const radius = ((hash + i * 31) % 15) + 2;
      points.push({
        x: cx + Math.cos(angle) * radius + ((i * 7) % 5),
        y: cy + Math.sin(angle) * radius + ((i * 11) % 5),
        z: cpv.n,
        cluster: cpv.descripcion || cpv.cpv,
      });
    }
  });

  return { points, clusters: top };
}

export default function ClustersPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["analytics", "overview"],
    queryFn: fetchOverview,
    staleTime: 5 * 60 * 1000,
  });

  const cpvs = data?.por_cpv ?? [];
  const topCpvs = useMemo(() => cpvs.slice(0, 10), [cpvs]);

  type CpvItem = { cpv: string; descripcion?: string; n: number };
  const cpvColumns = useMemo<ColumnDef<CpvItem>[]>(
    () => [
      {
        accessorKey: "cpv",
        header: "CPV",
        cell: ({ getValue }) => (
          <span className="font-mono text-xs">{getValue<string>()}</span>
        ),
      },
      {
        accessorKey: "descripcion",
        header: "Descripcion",
        cell: ({ getValue }) => {
          const v = getValue<string | undefined>();
          return (
            <span className="max-w-xs truncate block" title={v}>
              {v || "-"}
            </span>
          );
        },
      },
      {
        accessorKey: "n",
        header: "Licitaciones",
        cell: ({ getValue }) => (
          <span className="tabular-nums text-right block">
            {formatNumber(getValue<number>())}
          </span>
        ),
      },
    ],
    [],
  );

  const pieData = useMemo(() => {
    if (topCpvs.length === 0) return [];
    const topItems = topCpvs.map((c) => ({
      name: c.descripcion || c.cpv,
      value: c.n,
    }));
    const totalTop = topItems.reduce((s, i) => s + i.value, 0);
    const totalAll = (data?.total_licitaciones ?? 0);
    if (totalAll > totalTop) {
      topItems.push({ name: "Otros CPVs", value: totalAll - totalTop });
    }
    return topItems;
  }, [topCpvs, data]);

  const mockScatter = useMemo(() => {
    if (cpvs.length === 0) return null;
    return generateMockScatter(cpvs);
  }, [cpvs]);

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
        <h1 className="text-2xl font-bold tracking-tight">Clusters</h1>
        <p className="text-muted-foreground">
          Agrupacion semantica de licitaciones.
        </p>
      </div>

      {/* Coming Soon Banner */}
      <Card className="border-dashed border-amber-300 dark:border-amber-700 bg-amber-50/50 dark:bg-amber-950/20">
        <CardContent className="flex items-start gap-4 py-6">
          <div className="rounded-lg bg-amber-100 dark:bg-amber-900/50 p-3">
            <FlaskConical className="h-6 w-6 text-amber-600 dark:text-amber-400" />
          </div>
          <div className="flex-1">
            <h3 className="font-semibold text-amber-900 dark:text-amber-200">
              Clustering Semantico — Proximamente
            </h3>
            <p className="mt-1 text-sm text-amber-800/80 dark:text-amber-300/80">
              La agrupacion semantica completa requiere una pipeline de ML con generacion de
              embeddings (sentence-transformers), reduccion dimensional (UMAP) y clustering
              (HDBSCAN). Mientras tanto, mostramos una vista previa basada en agrupacion por
              codigos CPV como pseudo-clusters.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge variant="secondary">Embeddings</Badge>
              <Badge variant="secondary">UMAP</Badge>
              <Badge variant="secondary">HDBSCAN</Badge>
              <Badge variant="secondary">sentence-transformers</Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          title="Total Licitaciones"
          value={isLoading ? undefined : formatNumber(data?.total_licitaciones ?? 0)}
          subtitle="disponibles para clustering"
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title="Pseudo-Clusters (CPVs)"
          value={isLoading ? undefined : formatNumber(cpvs.length)}
          subtitle="codigos CPV unicos"
          icon={Waypoints}
          loading={isLoading}
        />
        <KpiCard
          title="Top CPV"
          value={
            isLoading
              ? undefined
              : topCpvs.length > 0
                ? (topCpvs[0].descripcion || topCpvs[0].cpv).slice(0, 35)
                : "-"
          }
          subtitle={topCpvs.length > 0 ? `${formatNumber(topCpvs[0].n)} licitaciones` : undefined}
          icon={Sparkles}
          loading={isLoading}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Mock Scatter Plot */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Waypoints className="h-4 w-4" />
              Vista Previa: Proyeccion 2D (simulada)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : mockScatter && mockScatter.points.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={400}>
                <ScatterChart margin={{ top: 10, right: 10, bottom: 10, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis
                    type="number"
                    dataKey="x"
                    name="UMAP-1"
                    tick={{ fontSize: 10 }}
                    label={{ value: "UMAP-1 (simulado)", position: "bottom", fontSize: 11 }}
                  />
                  <YAxis
                    type="number"
                    dataKey="y"
                    name="UMAP-2"
                    tick={{ fontSize: 10 }}
                    label={{
                      value: "UMAP-2 (simulado)",
                      angle: -90,
                      position: "insideLeft",
                      fontSize: 11,
                    }}
                  />
                  <ZAxis type="number" dataKey="z" range={[20, 200]} />
                  <Tooltip
                    cursor={{ strokeDasharray: "3 3" }}
                    content={({ payload }) => {
                      if (!payload || payload.length === 0) return null;
                      const d = payload[0].payload;
                      return (
                        <div className="rounded-lg border bg-background p-2 text-xs shadow-md">
                          <p className="font-medium">{d.cluster}</p>
                        </div>
                      );
                    }}
                  />
                  {mockScatter.clusters.map((cluster, idx) => (
                    <Scatter
                      key={cluster.cpv}
                      name={cluster.descripcion || cluster.cpv}
                      data={mockScatter.points.filter(
                        (p) => p.cluster === (cluster.descripcion || cluster.cpv),
                      )}
                      fill={getSeriesColor(idx)}
                      opacity={0.7}
                    />
                  ))}
                </ScatterChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos</p>
            )}
            <p className="mt-2 text-xs text-muted-foreground text-center">
              Simulacion basada en CPVs. El clustering real usara embeddings + UMAP.
            </p>
          </CardContent>
        </Card>

        {/* Pie Chart: Top 10 CPVs */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Top 10 CPVs (Pseudo-Clusters)</CardTitle>
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
                    innerRadius={60}
                    outerRadius={130}
                    label={({ name, percent }: { name?: string; percent?: number }) =>
                      `${(name ?? "").length > 20 ? (name ?? "").slice(0, 20) + "..." : (name ?? "")} (${((percent ?? 0) * 100).toFixed(1)}%)`
                    }
                    labelLine={{ strokeWidth: 1 }}
                  >
                    {pieData.map((_, idx) => (
                      <Cell key={idx} fill={getSeriesColor(idx)} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value) => formatNumber(value as number)} />
                  <Legend
                    formatter={(value) =>
                      (value as string).length > 30 ? (value as string).slice(0, 30) + "..." : value
                    }
                  />
                </PieChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* CPV Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Agrupacion por CPV</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <DataTable
              columns={cpvColumns}
              data={cpvs}
              initialSorting={[{ id: "n", desc: true }]}
              emptyMessage="Sin datos CPV disponibles"
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
