import { Skeleton } from "@/components/ui/skeleton";

/**
 * Lo que pinta la ficha de empresa mientras llega: cabecera, tira de cifras y
 * el primer bloque, con las cotas de la ficha real.
 *
 * Fichero propio y sin `"use client"` para que el `loading.tsx` de Competencia
 * lo pinte sin arrastrar `CompanyProfile` entero a su chunk.
 */
export function ProfileSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-44 w-full rounded-xl" />
      <Skeleton className="h-40 w-full rounded-xl" />
      <Skeleton className="h-80 w-full rounded-xl" />
    </div>
  );
}
