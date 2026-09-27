import { SpaceShellEsqueleto } from "@/components/layout/space-shell-esqueleto";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta de Mi Watchlist con la forma de la página: el marco del
 * espacio, las dos pestañas, el formulario de alta abierto y la rejilla de
 * reglas. Antes era un título y tarjetas sueltas que la página no tiene.
 */
export default function MiWatchlistLoading() {
  return (
    <SpaceShellEsqueleto spaceKey="mi-watchlist">
      <div className="space-y-6">
        <Skeleton className="h-7 w-44 rounded-md" />
        <Skeleton className="h-48 w-full rounded-xl" />
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-36 w-full rounded-xl" />
          ))}
        </div>
      </div>
    </SpaceShellEsqueleto>
  );
}
