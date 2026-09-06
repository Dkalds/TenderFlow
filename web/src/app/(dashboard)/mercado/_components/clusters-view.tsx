"use client";

/**
 * Vista compartida por la ruta `/clusters` y por `?vista=clusters` del espacio
 * Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo no vive
 * en el `page.tsx` de la ruta.
 *
 * Es una de las dos vistas `experimental` del espacio (`lib/space-views.ts`),
 * así que se monta detrás de `VistaExperimental`: la flag `mercado_clusters`
 * puede apagarla desde Ops, y sin backend de flags sigue visible y marcada.
 */

import dynamic from "next/dynamic";

import { EmptyState } from "@/components/ui/empty-state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { BarChart3 } from "lucide-react";

import { useClustersView } from "../_hooks/use-clusters-view";
import { ClustersControles, ClustersKpis } from "./clusters-controles";
import { ClusterDetalleTabla, ClustersResumenTabla } from "./clusters-tablas";
import { VistaExperimental } from "./vista-experimental";

const ClustersBarChart = dynamic(() => import("@/components/charts/clusters-charts").then(m => ({ default: m.ClustersBarChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });
const ClustersBoxChart = dynamic(() => import("@/components/charts/clusters-charts").then(m => ({ default: m.ClustersBoxChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });

export default function ClustersView() {
  return (
    <VistaExperimental
      flag="mercado_clusters"
      vista="clusters"
      descripcion="Agrupación semántica de licitaciones por similitud de título (KMeans)."
    >
      <ClustersContenido />
    </VistaExperimental>
  );
}

function ClustersContenido() {
  const {
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
  } = useClustersView();

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
          Agrupación semántica de licitaciones por similitud de título (KMeans).
        </p>
      </div>

      <ClustersControles
        kDraft={kDraft}
        onKDraftChange={setKDraft}
        autoK={autoK}
        onAutoKChange={setAutoK}
        onRecalcular={recalcular}
        isFetching={isFetching}
      />

      <ClustersKpis data={data} clusters={clusters} autoK={autoK} isLoading={isLoading} />

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
            <CardTitle className="text-base">Distribución de importe por cluster</CardTitle>
            <CardDescription>
              Banda = rango (mín-máx), núcleo = rango intercuartílico (Q1-Q3)
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

      <ClustersResumenTabla
        clusters={clusters}
        isLoading={isLoading}
        onSelect={setSelectedCluster}
      />

      {clusters.length > 0 && selected && (
        <ClusterDetalleTabla
          clusters={clusters}
          selected={selected}
          onSelect={setSelectedCluster}
        />
      )}
    </div>
  );
}
