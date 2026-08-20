import FeatureFlagsView from "../ops/_components/feature-flags-view";

/**
 * Boundary de ruta. El cuerpo vive en `ops/_components/feature-flags-view`
 * porque el espacio Ops monta la misma vista bajo `?vista=flags`. La guarda de
 * administrador va dentro de esa vista, no en el layout.
 */
export default function FeatureFlagsPage() {
  return <FeatureFlagsView />;
}
