import ObservabilidadView from "../ops/_components/observabilidad-view";

/**
 * Boundary de ruta. El cuerpo vive en `ops/_components/observabilidad-view`
 * porque el espacio Ops monta la misma vista bajo `?vista=observabilidad`;
 * aquí sólo queda la entrada de ruta, con su `metadata` en el layout.
 */
export default function ObservabilidadPage() {
  return <ObservabilidadView />;
}
