import { SpaceShellEsqueleto } from "@/components/layout/space-shell-esqueleto";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta de Ajustes: el marco del espacio con una pestaña por vista
 * y, dentro, el mismo bloque que pinta cada vista mientras llega su chunk (el
 * `loading` de `next/dynamic` en `ajustes/page.tsx`). Caía en el genérico de
 * `(dashboard)/loading.tsx`, sin las pestañas del espacio.
 */
export default function AjustesLoading() {
  return (
    <SpaceShellEsqueleto spaceKey="ajustes">
      <Skeleton className="h-[320px] w-full rounded-xl" />
    </SpaceShellEsqueleto>
  );
}
