import { Skeleton } from "@/components/ui/skeleton";

/**
 * Carga de /detalle con la forma de la pantalla que llega: la barra de la
 * tabla, las filas y el pie de paginación, a toda la altura del marco. Antes
 * era una tarjeta con título y buscador que la página no tiene, y al llegar el
 * dato todo saltaba de sitio.
 */
export default function DetalleLoading() {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-11 flex-none items-center gap-2.5 border-b border-border/60 px-3.5">
        <Skeleton className="h-4 w-16" />
        <div className="flex-1" />
        <Skeleton className="h-6 w-36" />
      </div>
      <div className="min-h-0 flex-1 space-y-1.5 overflow-hidden px-3.5 py-2">
        {Array.from({ length: 14 }, (_, i) => (
          <Skeleton key={i} className="h-7 w-full rounded-sm" />
        ))}
      </div>
      <div className="flex h-11 flex-none items-center gap-3 border-t border-border/70 px-3.5">
        <Skeleton className="h-4 w-40" />
        <div className="flex-1" />
        <Skeleton className="h-6 w-48" />
      </div>
    </div>
  );
}
