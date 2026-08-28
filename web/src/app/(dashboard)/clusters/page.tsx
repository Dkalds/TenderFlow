import ClustersView from "../mercado/_components/clusters-view";

/**
 * Boundary de ruta. El cuerpo vive en `mercado/_components/clusters-view`
 * porque el espacio Mercado monta la misma vista bajo `?vista=clusters`.
 */
export default function ClustersPage() {
  return <ClustersView />;
}
