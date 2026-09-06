"use client";

/**
 * Controles del KMeans (k y auto-k) y la tira de KPIs del resultado.
 *
 * Van juntos porque responden a la misma pregunta —«¿este agrupamiento vale
 * algo?»—: el silhouette de la tira es lo que dice si el `k` del slider fue
 * buena idea.
 */

import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
import { formatNumber, truncate } from "@/lib/utils";
import { Waypoints, Hash, Layers, RefreshCw, Gauge } from "lucide-react";

import type { ClusterEntry, ClustersResponse } from "../_hooks/use-clusters-view";

export function ClustersControles({
  kDraft,
  onKDraftChange,
  autoK,
  onAutoKChange,
  onRecalcular,
  isFetching,
}: {
  kDraft: number;
  onKDraftChange: (k: number) => void;
  autoK: boolean;
  onAutoKChange: (auto: boolean) => void;
  onRecalcular: () => void;
  isFetching: boolean;
}) {
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-6 py-4">
        <div className="flex min-w-[240px] flex-1 flex-col gap-2">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">Número de clusters</span>
            <span className="tabular-nums text-muted-foreground">{autoK ? "auto" : kDraft}</span>
          </div>
          <Slider
            min={3}
            max={20}
            step={1}
            value={[kDraft]}
            onValueChange={(v) => onKDraftChange(v[0])}
            disabled={autoK}
          />
        </div>
        <label htmlFor="cl-autok" className="flex items-center gap-2 text-sm">
          <Switch id="cl-autok" checked={autoK} onCheckedChange={onAutoKChange} />
          Auto-optimizar k
        </label>
        <Button onClick={onRecalcular} disabled={isFetching} className="gap-2">
          <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          Recalcular
        </Button>
      </CardContent>
    </Card>
  );
}

export function ClustersKpis({
  data,
  clusters,
  autoK,
  isLoading,
}: {
  data: ClustersResponse | undefined;
  clusters: ClusterEntry[];
  autoK: boolean;
  isLoading: boolean;
}) {
  return (
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
  );
}
