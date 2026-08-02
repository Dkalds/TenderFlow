"use client";
import { EmptyState } from "@/components/ui/empty-state";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
const ClustersBarChart = dynamic(() => import("@/components/charts/clusters-charts").then(m => ({ default: m.ClustersBarChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });
const ClustersBoxChart = dynamic(() => import("@/components/charts/clusters-charts").then(m => ({ default: m.ClustersBoxChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton, SkeletonTable } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCurrency, formatNumber, truncate } from "@/lib/utils";
import { getSeriesColor } from "@/lib/chart-colors";
import { Waypoints, Hash, Layers, RefreshCw, BarChart3, Gauge } from "lucide-react";
import type { BoxDatum } from "@/components/charts/clusters-charts";

interface ImporteBox {
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
}

interface ClusterItem {
  id_externo: string;
  titulo: string | null;
  organo_contratacion: string | null;
  importe: number | null;
  ccaa: string | null;
  estado: string | null;
}

interface ClusterEntry {
  cluster_id: number;
  label: string;
  n: number;
  importe_medio: number;
  importe_total: number;
  cpv_dominante?: string | null;
  organo_dominante?: string | null;
  importe_box: ImporteBox | null;
  items: ClusterItem[];
}

interface ClustersResponse {
  n_clusters_detectados: number;
  total: number;
  silhouette?: number | null;
  clusters: ClusterEntry[];
}

export default function ClustersPage() {
  const [kDraft, setKDraft] = useState(8);
  const [appliedK, setAppliedK] = useState(8);
  const [autoK, setAutoK] = useState(false);
  const [selectedCluster, setSelectedCluster] = useState<number | null>(null);

  const { data, isLoading, isFetching, error, refetch } = useFilteredQuery<ClustersResponse>(
    ["analytics", "clusters", String(appliedK), String(autoK)],
    "/api/v1/analytics/clusters",
    { staleTime: 30 * 60 * 1000 },
    { n_clusters: String(appliedK), auto_k: String(autoK) },
  );

  const clusters = useMemo(() => data?.clusters ?? [], [data]);

  const barData = useMemo(
    () =>
      clusters.map((c) => ({
        label: truncate(c.label, 38) || `Cluster ${c.cluster_id}`,
        n: c.n,
        cluster_id: c.cluster_id,
      })),
    [clusters],
  );

  const boxData = useMemo<BoxDatum[]>(
    () =>
      clusters
        .filter((c) => c.importe_box)
        .map((c, i) => {
          const b = c.importe_box!;
          return {
            label: truncate(c.label, 32) || `Cluster ${c.cluster_id}`,
            _pad: b.min,
            _low: b.q1 - b.min,
            _boxLow: b.median - b.q1,
            _boxHigh: b.q3 - b.median,
            _high: b.max - b.q3,
            min: b.min,
            q1: b.q1,
            median: b.median,
            q3: b.q3,
            max: b.max,
            color: getSeriesColor(i),
          };
        }),
    [clusters],
  );

  const selected = useMemo(() => {
    if (clusters.length === 0) return null;
    return clusters.find((c) => c.cluster_id === selectedCluster) ?? clusters[0];
  }, [clusters, selectedCluster]);

  function recalcular() {
    setAppliedK(kDraft);
    void refetch();
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="sr-only">Clusters</h1>
        <p className="text-muted-foreground">
          Agrupacion semantica de licitaciones por similitud de titulo (KMeans).
        </p>
      </div>

      {/* Controls */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-6 py-4">
          <div className="flex min-w-[240px] flex-1 flex-col gap-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">Numero de clusters</span>
              <span className="tabular-nums text-muted-foreground">{autoK ? "auto" : kDraft}</span>
            </div>
            <Slider
              min={3}
              max={20}
              step={1}
              value={[kDraft]}
              onValueChange={(v) => setKDraft(v[0])}
              disabled={autoK}
            />
          </div>
          <label htmlFor="cl-autok" className="flex items-center gap-2 text-sm">
            <Switch id="cl-autok" checked={autoK} onCheckedChange={setAutoK} />
            Auto-optimizar k
          </label>
          <Button onClick={recalcular} disabled={isFetching} className="gap-2">
            <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            Recalcular
          </Button>
        </CardContent>
      </Card>

      {/* KPIs */}
      <KpiStrip columns={4}>
        <KpiCard
          title="Clusters detectados"
          value={isLoading ? undefined : formatNumber(data?.n_clusters_detectados ?? 0)}
          subtitle={autoK ? "auto (silhouette)" : undefined}
          icon={Waypoints}
          loading={isLoading}
        />
        <KpiCard
          title="Calidad (silhouette)"
          value={
            isLoading || data?.silhouette == null
              ? undefined
              : data.silhouette.toFixed(2)
          }
          subtitle={
            data?.silhouette == null
              ? "no disponible"
              : data.silhouette >= 0.5
                ? "Buena separación"
                : data.silhouette >= 0.25
                  ? "Separación moderada"
                  : "Separación débil — prueba otro k"
          }
          icon={Gauge}
          loading={isLoading}
        />
        <KpiCard
          title="Licitaciones agrupadas"
          value={isLoading ? undefined : formatNumber(data?.total ?? 0)}
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title="Cluster mayor"
          value={
            isLoading
              ? undefined
              : clusters.length > 0
                ? truncate(clusters[0].label, 28)
                : "-"
          }
          subtitle={clusters.length > 0 ? `${formatNumber(clusters[0].n)} licitaciones` : undefined}
          icon={Layers}
          loading={isLoading}
        />
      </KpiStrip>

      {data && data.total > 0 && clusters.length === 0 && (
        <div className="rounded-lg border border-amber-300 bg-amber-50/50 p-4 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950/20 dark:text-amber-300">
          No se pudieron generar clusters para el conjunto filtrado (datos insuficientes).
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Per-cluster bar */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <BarChart3 className="h-4 w-4" />
              Licitaciones por cluster
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : barData.length > 0 ? (
              <ClustersBarChart data={barData} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        {/* Importe distribution box plot */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Distribucion de importe por cluster</CardTitle>
            <CardDescription>
              Banda = rango (min-max), nucleo = rango intercuartilico (Q1-Q3)
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : boxData.length > 0 ? (
              <ClustersBoxChart data={boxData} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Cluster summary table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Resumen de clusters</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <SkeletonTable rows={6} />
          ) : (
            <div className="overflow-x-auto">
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow className="border-b text-left">
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">ID</TableHead>
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">Keywords</TableHead>
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">CPV dominante</TableHead>
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">Organo dominante</TableHead>
                    <TableHead className="pb-2 pr-4 text-right font-medium text-muted-foreground">Licitaciones</TableHead>
                    <TableHead className="pb-2 pr-4 text-right font-medium text-muted-foreground">Importe medio</TableHead>
                    <TableHead className="pb-2 text-right font-medium text-muted-foreground">Importe total</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {clusters.map((c) => (
                    <TableRow
                      key={c.cluster_id}
                      className="cursor-pointer border-b border-border/50 hover:bg-muted/50"
                      onClick={() => setSelectedCluster(c.cluster_id)}
                    >
                      <TableCell className="py-2 pr-4 tabular-nums">{c.cluster_id}</TableCell>
                      <TableCell className="max-w-md py-2 pr-4">
                        <span className="block truncate" title={c.label}>{c.label}</span>
                      </TableCell>
                      <TableCell className="max-w-[14rem] truncate py-2 pr-4 text-muted-foreground" title={c.cpv_dominante ?? ""}>
                        {c.cpv_dominante ?? "-"}
                      </TableCell>
                      <TableCell className="max-w-[12rem] truncate py-2 pr-4 text-muted-foreground" title={c.organo_dominante ?? ""}>
                        {c.organo_dominante ?? "-"}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">{formatNumber(c.n)}</TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">{formatCurrency(c.importe_medio)}</TableCell>
                      <TableCell className="py-2 text-right tabular-nums">{formatCurrency(c.importe_total)}</TableCell>
                    </TableRow>
                  ))}
                  {clusters.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                        Sin clusters
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Cluster drill-down */}
      {clusters.length > 0 && selected && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Licitaciones del cluster</CardTitle>
            <div className="mt-2">
              <Select
                value={String(selected.cluster_id)}
                onValueChange={(v) => setSelectedCluster(Number(v))}
              >
                <SelectTrigger className="w-full max-w-xl text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {clusters.map((c) => (
                    <SelectItem key={c.cluster_id} value={String(c.cluster_id)}>
                      Cluster {c.cluster_id}: {truncate(c.label, 50)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow className="border-b text-left">
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">Titulo</TableHead>
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">Organo</TableHead>
                    <TableHead className="pb-2 pr-4 text-right font-medium text-muted-foreground">Importe</TableHead>
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">CCAA</TableHead>
                    <TableHead className="pb-2 font-medium text-muted-foreground">Estado</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {selected.items.map((it) => (
                    <TableRow key={it.id_externo} className="border-b border-border/50 hover:bg-muted/50">
                      <TableCell className="max-w-sm py-2 pr-4 font-medium">
                        <span className="line-clamp-2" title={it.titulo ?? ""}>{it.titulo ?? "-"}</span>
                      </TableCell>
                      <TableCell className="max-w-[12rem] truncate py-2 pr-4" title={it.organo_contratacion ?? ""}>
                        {it.organo_contratacion ?? "-"}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {it.importe != null ? formatCurrency(it.importe) : "-"}
                      </TableCell>
                      <TableCell className="py-2 pr-4">{it.ccaa ?? "-"}</TableCell>
                      <TableCell className="py-2">{it.estado ?? "-"}</TableCell>
                    </TableRow>
                  ))}
                  {selected.items.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                        Sin licitaciones
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
