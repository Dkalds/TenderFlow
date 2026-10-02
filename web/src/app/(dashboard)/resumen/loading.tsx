import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta del Resumen.
 *
 * Pintaba todavía la pantalla de dos generaciones atrás —cuatro tarjetas de KPI
 * y una rejilla 2×2 de gráficos— que la página dejó de tener hace dos
 * rediseños: el usuario veía aparecer una estructura y llegar otra distinta.
 * Esto replica las bandas reales y sus altos, para que la carga no salte: la
 * cabecera sin borde (el borde lo pone el scroll), el campo del copiloto, «Tu
 * día», la banda de «Mercado abierto» con la cola a dos tercios y las dos
 * tarjetas apiladas, y la tira de contexto.
 */
export default function ResumenLoading() {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-11 flex-none items-center px-4">
        <Skeleton className="h-4 w-24 rounded-sm" />
      </div>
      <div className="min-h-0 flex-1 overflow-hidden px-4 pt-4 pb-6">
        {/* Copiloto */}
        <Skeleton className="mb-4 h-10 max-w-[720px] rounded-md" />

        {/* Tu día: tira de cuatro + lista de compromisos */}
        <Skeleton className="mb-2.5 h-4 w-28 rounded-sm" />
        <Skeleton className="mb-2.5 h-[72px] w-full rounded-xl" />
        <Skeleton className="mb-5.5 h-[104px] w-full rounded-xl" />

        {/* Mercado abierto: la cola a dos tercios y dos tarjetas apiladas */}
        <Skeleton className="mb-2.5 h-4 w-32 rounded-sm" />
        <div className="mb-5.5 grid gap-3 lg:grid-cols-3">
          <Skeleton className="h-[248px] rounded-xl lg:col-span-2" />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
            <Skeleton className="h-[118px] rounded-xl" />
            <Skeleton className="h-[118px] rounded-xl" />
          </div>
        </div>

        {/* Contexto de mercado */}
        <Skeleton className="mb-2.5 h-4 w-36 rounded-sm" />
        <Skeleton className="h-[72px] w-full rounded-xl" />
      </div>
    </div>
  );
}
