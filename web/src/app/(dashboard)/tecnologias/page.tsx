import TecnologiasView from "../mercado/_components/tecnologias-view";

/**
 * Boundary de ruta. El cuerpo vive en `mercado/_components/tecnologias-view`
 * porque el espacio Mercado monta la misma vista bajo `?vista=tecnologias`.
 */
export default function TecnologiasPage() {
  return <TecnologiasView />;
}
