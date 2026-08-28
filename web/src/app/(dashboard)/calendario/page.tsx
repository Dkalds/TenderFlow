import CalendarioView from "../mercado/_components/calendario-view";

/**
 * Boundary de ruta. El cuerpo vive en `mercado/_components/calendario-view`
 * porque el espacio Mercado monta la misma vista bajo `?vista=calendario`.
 */
export default function CalendarioPage() {
  return <CalendarioView />;
}
