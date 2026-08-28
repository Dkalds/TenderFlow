import TendenciasView from "../mercado/_components/tendencias-view";

/**
 * Boundary de ruta. El cuerpo vive en `mercado/_components/tendencias-view`
 * porque el espacio Mercado monta la misma vista bajo `?vista=tiempo`; aquí
 * sólo queda la entrada de ruta, con su `metadata` en el layout.
 */
export default function TendenciasPage() {
  return <TendenciasView />;
}
