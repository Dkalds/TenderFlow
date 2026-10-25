import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta del Resumen.
 *
 * Replica las bandas reales y sus altos para que la carga no salte: la
 * cabecera sin borde (el borde lo pone el scroll), el campo del asistente y
 * las dos zonas de `resumen-view.tsx`. Lo tuyo: «Tu día» con sus contadores y
 * la semana, y la banda de «Desde tu última visita». El mercado, tras su
 * filete y su rótulo: la cola a dos tercios con las dos tarjetas apiladas, y
 * la tira del periodo con el ritmo y los movimientos al lado. Altos medidos a
 * 1440 px con datos y redondeados (2026-10), con cambios en «Desde tu última
 * visita» y compromisos en la semana, que es lo habitual.
 */
export default function ResumenLoading() {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-11 flex-none items-center px-4">
        <Skeleton className="h-4 w-24 rounded-sm" />
      </div>
      <div className="min-h-0 flex-1 overflow-hidden px-4 pt-4 pb-6">
        {/* Asistente */}
        <Skeleton className="mb-5 h-10 max-w-[720px] rounded-md" />

        <div className="flex flex-col gap-5">
          {/* Tu día: el rótulo, la tira de cuatro con sus puntos y la semana en carriles */}
          <div className="flex flex-col gap-2.5">
            <Skeleton className="h-4 w-28 rounded-sm" />
            <Skeleton className="h-[100px] w-full rounded-xl" />
            <Skeleton className="h-[260px] w-full rounded-xl" />
          </div>

          {/* Desde tu última visita: el reparto a la izquierda y los cambios a la derecha */}
          <Skeleton className="h-[180px] w-full rounded-xl" />
        </div>

        {/* Mercado: filete, rótulo y atajos */}
        <div className="mt-9 border-t border-divider pt-4">
          <Skeleton className="mb-4 h-5 w-28 rounded-sm" />

          {/* Abierto hoy: la cola a dos tercios, con su reloj, y dos tarjetas apiladas */}
          <div className="mb-5 grid gap-3 lg:grid-cols-3">
            <Skeleton className="h-[340px] rounded-xl lg:col-span-2" />
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
              <Skeleton className="h-[138px] rounded-xl" />
              <Skeleton className="h-[190px] rounded-xl" />
            </div>
          </div>

          {/* El periodo: la tira de tres y, debajo, el ritmo junto a los movimientos */}
          <Skeleton className="mb-2.5 h-[92px] w-full rounded-xl" />
          <div className="grid grid-cols-1 gap-2.5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <Skeleton className="h-[400px] w-full rounded-xl" />
            <Skeleton className="h-[400px] w-full rounded-xl" />
          </div>
        </div>
      </div>
    </div>
  );
}
