import { SpaceShellEsqueleto, VistaEsqueleto } from "@/components/layout/space-shell-esqueleto";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta de Ops y Admin: el marco del espacio con una pestaña por
 * vista, la tira de salud común (`OpsHealthStrip`, con su `mb-4`) y, debajo,
 * el mismo esqueleto que pinta cada vista mientras llega su chunk.
 */
export default function OpsLoading() {
  return (
    <SpaceShellEsqueleto spaceKey="ops">
      {/* Dos filas de celdas por debajo de `lg`, una a partir de ahí. */}
      <Skeleton className="mb-4 h-[166px] w-full rounded-xl lg:h-[83px]" />
      <VistaEsqueleto />
    </SpaceShellEsqueleto>
  );
}
