import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta del Resumen.
 *
 * Replica la rejilla real de `resumen-view.tsx` y sus altos para que la carga
 * no salte: la cabecera con el asistente a la derecha y tres filas. La
 * primera, «Tu día» y «Desde tu última visita» a la izquierda y, a la
 * derecha, el rótulo del mercado, las dos tarjetas y la cola de cierre. La
 * segunda, la tira del periodo sobre el gráfico, la composición y el mapa. La
 * tercera, la tabla y los movimientos. Altos medidos a 1440 px con datos y
 * redondeados (2026-10-31), con la semana plegada, que es como abre.
 */
export default function ResumenLoading() {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex min-h-11 flex-none flex-wrap items-center gap-x-2.5 gap-y-2 px-4 py-1.5">
        <Skeleton className="h-4 w-24 rounded-sm" />
        {/* Asistente */}
        <Skeleton className="h-9 w-full rounded-md sm:ml-auto sm:w-[380px]" />
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden px-4 pt-3 pb-6">
        {/* Fila 1: lo tuyo y el mercado de hoy */}
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <div className="flex flex-col gap-3">
            <Skeleton className="h-4 w-28 rounded-sm" />
            <Skeleton className="h-[100px] w-full rounded-xl" />
            <Skeleton className="h-[220px] w-full rounded-xl" />
          </div>
          <div className="flex flex-col gap-3">
            <Skeleton className="h-5 w-28 rounded-sm" />
            <div className="grid gap-3 sm:grid-cols-2">
              <Skeleton className="h-[138px] rounded-xl" />
              <Skeleton className="h-[138px] rounded-xl" />
            </div>
            <Skeleton className="h-[200px] w-full rounded-xl" />
          </div>
        </div>

        {/* Fila 2: el periodo, la composición y el mapa */}
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-[minmax(0,5fr)_minmax(0,3fr)_minmax(0,4fr)]">
          <div className="flex flex-col gap-3 lg:col-span-2 xl:col-span-1">
            <Skeleton className="h-[92px] w-full rounded-xl" />
            <Skeleton className="h-[320px] w-full rounded-xl" />
          </div>
          <Skeleton className="h-[424px] w-full rounded-xl" />
          <Skeleton className="h-[424px] w-full rounded-xl" />
        </div>
      </div>
    </div>
  );
}
