import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta con la forma real de la pantalla: cabecera, columna del
 * maestro y ficha al lado.
 *
 * Dibujaba un título y cuatro tarjetas de KPI, que era la silueta de la
 * pantalla anterior. Un esqueleto que promete una forma y entrega otra hace
 * saltar el layout justo cuando llega el dato, que es lo contrario de para lo
 * que está.
 */
export default function EmpresasLoading() {
  return (
    <div className="flex h-[calc(100vh-52px)] min-h-0 flex-col">
      <div className="border-border/60 flex h-11 flex-none items-center gap-3 border-b px-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-40" />
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="border-border/60 flex w-[560px] flex-none flex-col gap-2 border-r p-4">
          <Skeleton className="mb-1 h-8 w-full rounded-lg" />
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full rounded-md" />
          ))}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-3 p-5">
          {[72, 64, 120, 140].map((height) => (
            <Skeleton key={height} className="w-full rounded-[10px]" style={{ height }} />
          ))}
        </div>
      </div>
    </div>
  );
}
