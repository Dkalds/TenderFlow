import TendenciasCpvView from "../mercado/_components/tendencias-cpv-view";

/**
 * Boundary de ruta. El cuerpo vive en `mercado/_components/tendencias-cpv-view`
 * porque el espacio Mercado monta la misma vista bajo `?vista=cpv`.
 */
export default function TendenciasCpvPage() {
  return <TendenciasCpvView />;
}
