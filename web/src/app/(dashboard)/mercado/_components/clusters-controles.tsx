"use client";

/**
 * Controles del agrupamiento (k y auto-k) y la tira de KPIs del resultado.
 *
 * Van juntos porque responden a la misma pregunta —«¿este agrupamiento vale
 * algo?»—: la calidad de la tira es lo que dice si el `k` del slider fue buena
 * idea.
 */

import { Panel, StatCell, StatStrip } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { EMPTY, formatNumber, truncate } from "@/lib/utils";
import { Loader2 } from "lucide-react";

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
    <Panel className="flex flex-wrap items-center gap-6">
      <div className="flex min-w-[240px] flex-1 flex-col gap-2">
        <div className="flex items-center justify-between text-tf-meta">
          <span className="font-medium">Número de clusters</span>
          <span className="text-muted-foreground">{autoK ? "Automático" : kDraft}</span>
        </div>
        <Slider
          min={3}
          max={20}
          step={1}
          value={[kDraft]}
          onValueChange={(v) => onKDraftChange(v[0])}
          disabled={autoK}
          aria-label="Número de clusters"
        />
      </div>
      <label htmlFor="cl-autok" className="flex items-center gap-2 text-tf-meta">
        <Switch id="cl-autok" checked={autoK} onCheckedChange={onAutoKChange} />
        Elegir el número automáticamente
      </label>
      <Button size="sm" variant="outline" onClick={onRecalcular} disabled={isFetching}>
        {isFetching && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />}
        Recalcular
      </Button>
    </Panel>
  );
}

/** La calidad del agrupamiento (silhouette), en palabras. */
function lecturaCalidad(silhouette: number | null | undefined): string {
  if (silhouette == null) return "No disponible";
  if (silhouette >= 0.5) return "Grupos bien separados";
  if (silhouette >= 0.25) return "Separación moderada";
  return "Separación débil: prueba otro número";
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
  const silhouette = data?.silhouette;
  return (
    <StatStrip columns={4}>
      <StatCell
        label="Clusters detectados"
        value={formatNumber(data?.n_clusters_detectados ?? 0)}
        hint={autoK ? "Número elegido automáticamente" : undefined}
        loading={isLoading}
      />
      <StatCell
        label="Calidad del agrupamiento"
        value={silhouette == null ? EMPTY : silhouette.toFixed(2).replace(".", ",")}
        hint={lecturaCalidad(silhouette)}
        loading={isLoading}
      />
      <StatCell label="Licitaciones agrupadas" value={formatNumber(data?.total ?? 0)} loading={isLoading} />
      <StatCell
        label="Cluster más grande"
        value={clusters.length > 0 ? truncate(clusters[0].label, 28) : EMPTY}
        hint={clusters.length > 0 ? `${formatNumber(clusters[0].n)} licitaciones` : undefined}
        loading={isLoading}
      />
    </StatStrip>
  );
}
