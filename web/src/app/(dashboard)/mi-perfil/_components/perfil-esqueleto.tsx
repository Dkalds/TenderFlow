import { Skeleton } from "@/components/ui/skeleton";

/**
 * Lo que pinta Mi perfil mientras llega el perfil: la columna de la página con
 * sus primeros bloques. Lo comparten el `loading.tsx` de la ruta y el estado de
 * carga de la página. Sin `"use client"`: el `loading.tsx` es de servidor.
 */
export function PerfilEsqueleto() {
  return (
    <div className="max-w-2xl space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-64 w-full rounded-xl" />
      <Skeleton className="h-48 w-full rounded-xl" />
    </div>
  );
}
