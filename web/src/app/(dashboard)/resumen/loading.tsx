import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta del Resumen.
 *
 * Replica la rejilla real de `resumen-view.tsx` para que la carga no salte:
 * la cabecera con el asistente a la derecha y las tres primeras filas — lo de
 * hoy («Tu día» y la cola de cierre), lo tuyo («Para ti» y «Tus
 * oportunidades») y el mercado («Mercado hoy» y «Lo que sigues»). Altos
 * aproximados a 1440 px con datos, con la semana plegada, que es como abre.
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
        {/* Fila 1: Tu día y la cola de cierre */}
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <Skeleton className="h-[320px] w-full rounded-xl" />
          <Skeleton className="h-[320px] w-full rounded-xl" />
        </div>

        {/* Fila 2: Para ti y Tus oportunidades */}
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          <Skeleton className="h-[360px] w-full rounded-xl" />
          <Skeleton className="h-[360px] w-full rounded-xl" />
        </div>

        {/* Fila 3: Mercado hoy y Lo que sigues */}
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,8fr)_minmax(0,4fr)]">
          <Skeleton className="h-[480px] w-full rounded-xl" />
          <Skeleton className="h-[480px] w-full rounded-xl" />
        </div>
      </div>
    </div>
  );
}
