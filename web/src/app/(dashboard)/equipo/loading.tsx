import { SpaceShellEsqueleto } from "@/components/layout/space-shell-esqueleto";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta de Equipo: la cabecera del espacio (sin pestañas de
 * espacio: Equipo no tiene vistas en `SPACE_VIEWS`) y la forma de la página,
 * el panel de «Crear organización» y el bloque de la pestaña activa.
 */
export default function EquipoLoading() {
  return (
    <SpaceShellEsqueleto spaceKey="equipo">
      <div className="space-y-5">
        <Skeleton className="h-28 w-full rounded-xl" />
        <Skeleton className="h-[320px] w-full rounded-xl" />
      </div>
    </SpaceShellEsqueleto>
  );
}
