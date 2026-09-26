import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta del Radar, con las mismas cotas que `RadarView`: la barra
 * de controles (h-11 desde `lg`), la lista de filas, el pie de estado de 34 px
 * y, desde `xl`, el inspector de 432 px con su borde. Hasta que el prefetch se
 * movió del layout a la página el Radar no podía tener uno propio y se veía el
 * genérico del dashboard, con tarjetas que la pantalla no tiene.
 *
 * Sin `"use client"`: un `loading.tsx` de servidor no carga JavaScript para
 * pintarse.
 */
export default function RadarLoading() {
  return (
    <div className="flex h-full min-h-0">
      <section className="xl:border-border/70 flex min-w-0 flex-1 flex-col xl:border-r">
        <div className="border-border/60 flex min-h-11 flex-none items-center gap-2 border-b px-3 py-2 md:px-3.5 lg:h-11 lg:py-0">
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-7 w-20 rounded-md" />
          ))}
        </div>
        <div className="min-h-0 flex-1 space-y-2 overflow-hidden px-3 pt-3 md:px-3.5">
          {Array.from({ length: 10 }, (_, index) => (
            <Skeleton key={index} data-slot="fila-esqueleto" className="h-11 w-full rounded-md" />
          ))}
        </div>
        <div className="border-border/70 flex h-[34px] flex-none items-center border-t px-3 md:px-3.5">
          <Skeleton className="h-3 w-48 rounded" />
        </div>
      </section>
      <aside className="hidden w-[432px] flex-none flex-col gap-3 p-4 xl:flex">
        <Skeleton className="h-5 w-3/4 rounded" />
        <Skeleton className="h-4 w-1/2 rounded" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </aside>
    </div>
  );
}
