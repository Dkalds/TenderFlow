"use client";

/**
 * Estado y series de la vista Clusters.
 *
 * El `k` tiene dos valores a propósito: `kDraft` es lo que mueve el slider y
 * `appliedK` lo que viaja a la API. Sin esa separación, arrastrar el control
 * lanzaría un KMeans por cada píxel.
 */

import { useMemo, useState } from "react";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import type { BoxDatum } from "@/components/charts/clusters-charts";
import { getSeriesColor } from "@/lib/chart-colors";
import { truncate } from "@/lib/utils";

export interface ImporteBox {
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
}

export interface ClusterItem {
  id_externo: string;
  titulo: string | null;
  organo_contratacion: string | null;
  importe: number | null;
  ccaa: string | null;
  estado: string | null;
}

export interface ClusterEntry {
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

export interface ClustersResponse {
  n_clusters_detectados: number;
  total: number;
  silhouette?: number | null;
  clusters: ClusterEntry[];
}

export interface BarDatum {
  label: string;
  n: number;
  cluster_id: number;
}

export function useClustersView() {
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

  const barData = useMemo<BarDatum[]>(
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

  return {
    data,
    clusters,
    barData,
    boxData,
    selected,
    setSelectedCluster,
    kDraft,
    setKDraft,
    autoK,
    setAutoK,
    recalcular,
    isLoading,
    isFetching,
    error,
  };
}
