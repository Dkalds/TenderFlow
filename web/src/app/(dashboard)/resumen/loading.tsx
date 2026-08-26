import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta del Resumen.
 *
 * Pintaba todavía la pantalla de dos generaciones atrás —cuatro tarjetas de KPI
 * y una rejilla 2×2 de gráficos— que la página dejó de tener hace dos
 * rediseños: el usuario veía aparecer una estructura y llegar otra distinta.
 * Esto replica las bandas reales y sus altos, para que la carga no salte.
 */
export default function ResumenLoading() {
  return (
    <div className="flex h-[calc(100vh-52px)] min-h-0 flex-col">
      <div className="border-border/60 flex h-11 flex-none items-center border-b px-4">
        <Skeleton className="h-4 w-24 rounded" />
      </div>
      <div className="min-h-0 flex-1 overflow-hidden px-4 pt-4 pb-6">
        {/* Copiloto */}
        <Skeleton className="mb-4 h-[46px] max-w-[720px] rounded-xl" />

        {/* Tu día: tira de cuatro + lista de compromisos */}
        <Skeleton className="mb-2.5 h-4 w-28 rounded" />
        <Skeleton className="mb-2.5 h-[72px] w-full rounded-xl" />
        <Skeleton className="mb-5.5 h-[104px] w-full rounded-xl" />

        {/* Mercado abierto: banner de novedades + cuatro tarjetas */}
        <Skeleton className="mb-2.5 h-4 w-32 rounded" />
        <Skeleton className="mb-4 h-20 w-full rounded-xl" />
        <div className="mb-5.5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-[118px] rounded-xl" />
          ))}
        </div>

        {/* Contexto y salud competitiva */}
        <Skeleton className="mb-2.5 h-4 w-36 rounded" />
        <Skeleton className="mb-5.5 h-[72px] w-full rounded-xl" />
        <Skeleton className="mb-2.5 h-4 w-32 rounded" />
        <Skeleton className="h-[72px] w-full rounded-xl" />
      </div>
    </div>
  );
}
