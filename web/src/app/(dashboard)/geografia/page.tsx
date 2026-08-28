import GeografiaView from "../mercado/_components/geografia-view";

/**
 * Boundary de ruta. El cuerpo vive en `mercado/_components/geografia-view`
 * porque el espacio Mercado monta la misma vista bajo `?vista=geografia`.
 */
export default function GeografiaPage() {
  return <GeografiaView />;
}
