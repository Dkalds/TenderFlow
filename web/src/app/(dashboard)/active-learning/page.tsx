import ActiveLearningView from "../ops/_components/active-learning-view";

/**
 * Boundary de ruta. El cuerpo vive en `ops/_components/active-learning-view`
 * porque el espacio Ops monta la misma vista bajo `?vista=etiquetado`. La
 * guarda de administrador va dentro de esa vista, no en el layout.
 */
export default function ActiveLearningPage() {
  return <ActiveLearningView />;
}
