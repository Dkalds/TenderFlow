import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta del Investigador, en el orden de la pantalla: la caja de
 * consulta, las opciones avanzadas plegadas (una línea), las preguntas de
 * ejemplo y el vacío. Sin tarjetas: la pantalla ya no las usa.
 */
export default function InvestigadorLoading() {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Skeleton className="h-6 w-40 rounded-sm" />
        <Skeleton className="h-4 w-80 rounded-sm" />
      </div>
      <Skeleton className="h-[108px] w-full rounded-xl" />
      <Skeleton className="h-11 w-full rounded-xl" />
      <div className="flex flex-wrap gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-8 w-48 rounded-md" />
        ))}
      </div>
      <Skeleton className="h-32 w-full rounded-xl" />
    </div>
  );
}
