import { Skeleton } from "@/components/ui/skeleton";

/**
 * Lo que pinta la lista de cuentas mientras llega. Fichero propio y sin
 * `"use client"`: el `loading.tsx` de Cuentas lo pinta sin arrastrar la lista
 * entera a su chunk, y la lista pinta el mismo, así que no salta.
 */
export function ListaCuentasEsqueleto() {
  return (
    <div data-slot="lista-cuentas-esqueleto">
      <Skeleton className="h-40 w-full rounded-xl" />
    </div>
  );
}
