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

import { Aviso, Panel, PanelEmpty, PanelError, PanelLoading, PanelTitle } from "@/components/console/panel";

import { useClustersView } from "../_hooks/use-clusters-view";
import { ClustersControles, ClustersKpis } from "./clusters-controles";
import { ClusterDetalleTabla, ClustersResumenTabla } from "./clusters-tablas";
import { VistaExperimental } from "./vista-experimental";

const ClustersBarChart = dynamic(() => import("@/components/charts/clusters-charts").then(m => ({ default: m.ClustersBarChart })), { ssr: false, loading: () => <PanelLoading height={400} /> });
const ClustersBoxChart = dynamic(() => import("@/components/charts/clusters-charts").then(m => ({ default: m.ClustersBoxChart })), { ssr: false, loading: () => <PanelLoading height={400} /> });

export default function ClustersView() {
  return (
    <VistaExperimental
      flag="mercado_clusters"
      vista="clusters"
      descripcion="Licitaciones agrupadas por el parecido de sus títulos."
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
    refetch,
  } = useClustersView();

  if (error) {
    return <PanelError title="No se pudieron cargar los clusters" error={error} onRetry={refetch} />;
  }

  return (
    <div className="space-y-4">
      <h1 className="sr-only">Clusters</h1>

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
        <Aviso tone="warning">
          No hay licitaciones suficientes en el ámbito actual para formar grupos. Amplía las fechas o quita filtros.
        </Aviso>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelTitle title="Licitaciones por cluster" />
          {isLoading ? (
            <PanelLoading height={400} />
          ) : barData.length > 0 ? (
            <ClustersBarChart data={barData} />
          ) : (
            <PanelEmpty
              title="Ningún cluster"
              hint="No hay licitaciones agrupadas con el ámbito actual."
              height={400}
            />
          )}
        </Panel>

        <Panel>
          <PanelTitle title="Importe por cluster" className="mb-1" />
          <p className="mb-3 text-tf-meta text-muted-foreground">
            La banda va del mínimo al máximo; el núcleo, del primer al tercer cuartil.
          </p>
          {isLoading ? (
            <PanelLoading height={400} />
          ) : boxData.length > 0 ? (
            <ClustersBoxChart data={boxData} />
          ) : (
            <PanelEmpty
              title="Sin importes"
              hint="Ningún cluster tiene licitaciones con importe publicado."
              height={400}
            />
          )}
        </Panel>
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
