import CalidadDatosView from "../ops/_components/calidad-datos-view";

/**
 * Boundary de ruta. El cuerpo vive en `ops/_components/calidad-datos-view`
 * porque el espacio Ops monta la misma vista bajo `?vista=calidad`.
 */
export default function CalidadDatosPage() {
  return <CalidadDatosView />;
}
