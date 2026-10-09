/**
 * El esqueleto de Resultado con la forma de la pantalla: la barra del
 * periodo, las cuatro cifras, los dos paneles de dinero y pérdidas y los
 * cuatro cortes. Antes era un bloque de 256 px y la pantalla real, cinco veces
 * más alta, empujaba todo al llegar; lo usan la ruta (`loading.tsx`) y la
 * vista mientras llega el cuadro, para que el relevo no mueva nada.
 */
import { Skeleton } from "@/components/ui/skeleton";

export function DireccionEsqueleto() {
  return (
    <div className="flex flex-col gap-6" aria-hidden="true">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Skeleton className="h-4 w-72 rounded-sm" />
        <Skeleton className="h-7 w-64 rounded-md" />
      </div>
      <div className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-border/60 bg-border/60 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex flex-col gap-2 bg-card px-3.5 py-3">
            <Skeleton className="h-3 w-32 rounded-sm" />
            <Skeleton className="h-6 w-24 rounded-sm" />
            <Skeleton className="h-3 w-40 rounded-sm" />
            <Skeleton className="mt-2 h-3 w-16 rounded-sm" />
          </div>
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-64 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-56 w-full rounded-xl" />
        ))}
      </div>
    </div>
  );
}
