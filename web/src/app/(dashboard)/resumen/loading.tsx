import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta del Resumen.
 *
 * Pintaba todavía la pantalla de dos generaciones atrás —cuatro tarjetas de KPI
 * y una rejilla 2×2 de gráficos— que la página dejó de tener hace dos
 * rediseños: el usuario veía aparecer una estructura y llegar otra distinta.
 * Esto replica las bandas reales y sus altos, para que la carga no salte: la
 * cabecera sin borde (el borde lo pone el scroll), el campo del asistente, la
 * banda de «Desde tu última visita», «Tu día» con sus contadores y la semana,
 * la banda de «Mercado abierto» con la cola a dos tercios y las dos tarjetas
 * apiladas, y el contexto con su composición. Las cifras llevan su dibujo
 * debajo (puntos, áreas, el reloj de cierre), y los altos ya lo cuentan:
 * medidos a 1440 px con datos y redondeados (2026-10), con cambios en
 * «Desde tu última visita» y compromisos en la semana, que es lo habitual.
 */
export default function ResumenLoading() {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-11 flex-none items-center px-4">
        <Skeleton className="h-4 w-24 rounded-sm" />
      </div>
      <div className="min-h-0 flex-1 overflow-hidden px-4 pt-4 pb-6">
        {/* Asistente */}
        <Skeleton className="mb-4 h-10 max-w-[720px] rounded-md" />

        {/* Desde tu última visita: el reparto a la izquierda y los cambios a la derecha */}
        <Skeleton className="mb-3.5 h-[180px] w-full rounded-xl" />

        {/* Tu día: la tira de cuatro con sus puntos y, debajo, la semana en carriles */}
        <Skeleton className="mb-2.5 h-4 w-28 rounded-sm" />
        <Skeleton className="mb-2.5 h-[100px] w-full rounded-xl" />
        <Skeleton className="mb-5.5 h-[260px] w-full rounded-xl" />

        {/* Mercado abierto: la cola a dos tercios, con su reloj, y dos tarjetas apiladas */}
        <Skeleton className="mb-2.5 h-4 w-32 rounded-sm" />
        <div className="mb-5.5 grid gap-3 lg:grid-cols-3">
          <Skeleton className="h-[340px] rounded-xl lg:col-span-2" />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
            <Skeleton className="h-[138px] rounded-xl" />
            <Skeleton className="h-[190px] rounded-xl" />
          </div>
        </div>

        {/* Contexto de mercado: la tira de tres con sus áreas y la composición por estado */}
        <Skeleton className="mb-2.5 h-4 w-36 rounded-sm" />
        <Skeleton className="mb-2.5 h-[124px] w-full rounded-xl" />
        <Skeleton className="h-[220px] w-full rounded-xl" />
      </div>
    </div>
  );
}
