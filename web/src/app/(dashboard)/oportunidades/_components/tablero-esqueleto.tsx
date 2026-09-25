import { Skeleton } from "@/components/ui/skeleton";

/** Las cuatro celdas de `TableroMetricas`. */
const METRICAS = 4;

/**
 * Las que fija la rejilla del tablero (`xl:grid-cols-6`). No se cuenta `FASES`
 * para no arrastrar hasta un esqueleto los hooks de `use-pursuits`, que es de
 * donde ese módulo saca los estados.
 */
const COLUMNAS = 6;

/**
 * Esqueleto del tablero de Oportunidades con las bandas de `TableroView`: la
 * franja de métricas y una columna por fase con sus dos tarjetas de carga, a
 * las mismas alturas que pinta la vista mientras sus consultas están
 * pendientes. Así el relevo con la vista no mueve nada.
 */
export function TableroEsqueleto() {
  return (
    <div data-slot="tablero-esqueleto" className="flex h-full min-h-0 flex-col">
      <div className="border-border/70 bg-border/60 grid flex-none grid-cols-2 gap-px border-b lg:grid-cols-4">
        {Array.from({ length: METRICAS }, (_, indice) => (
          <div key={indice} className="bg-card px-3.5 py-2.5">
            <Skeleton className="mb-1.5 h-3 w-24 rounded" />
            <Skeleton className="h-5 w-20 rounded" />
            <Skeleton className="mt-1 h-3 w-32 rounded" />
          </div>
        ))}
      </div>
      <div className="bg-border/50 grid min-h-0 flex-1 grid-cols-1 gap-px md:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: COLUMNAS }, (_, indice) => (
          <div key={indice} className="bg-background flex min-h-0 min-w-0 flex-col">
            <div className="flex-none px-3 pt-2.5">
              <Skeleton className="h-4 w-24 rounded" />
              <Skeleton className="mt-1 h-7 w-full rounded" />
            </div>
            <div className="border-border/40 flex flex-col gap-2 border-t px-2.5 py-2.5">
              <Skeleton className="h-32 rounded-xl" />
              <Skeleton className="h-32 rounded-xl" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
