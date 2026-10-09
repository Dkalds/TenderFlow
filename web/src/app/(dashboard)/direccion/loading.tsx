import { SpaceShellEsqueleto } from "@/components/layout/space-shell-esqueleto";
import { DireccionEsqueleto } from "./_components/direccion-esqueleto";

/**
 * Esqueleto de ruta de Dirección: el marco del espacio con sus pestañas y la
 * misma forma que pinta Resultado mientras llega el cuadro
 * (`_components/direccion-esqueleto.tsx`), para que el relevo no mueva nada.
 */
export default function DireccionLoading() {
  return (
    <SpaceShellEsqueleto spaceKey="direccion">
      <DireccionEsqueleto />
    </SpaceShellEsqueleto>
  );
}
