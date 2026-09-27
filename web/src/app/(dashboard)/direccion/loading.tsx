import { SpaceShellEsqueleto } from "@/components/layout/space-shell-esqueleto";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta de Dirección: el marco del espacio con sus dos pestañas y
 * el mismo bloque que pinta la página mientras llega el cuadro
 * (`direccion/page.tsx`), para que el relevo no mueva nada.
 */
export default function DireccionLoading() {
  return (
    <SpaceShellEsqueleto spaceKey="direccion">
      <Skeleton className="h-64 w-full rounded-xl" />
    </SpaceShellEsqueleto>
  );
}
