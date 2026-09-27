import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de la ficha de una cuenta.
 *
 * Lo pintan el `loading.tsx` de Cuentas (al abrir `/cuentas/123` desde otro
 * espacio) y `page.tsx` mientras `useFichaCuenta` está pendiente: con un solo
 * componente para los dos, el relevo de la ruta a la página no se ve.
 */
export function FichaCuentaEsqueleto() {
  return (
    <div data-slot="ficha-cuenta-esqueleto" className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Skeleton className="h-24 w-full rounded-xl" />
      <Skeleton className="h-[360px] w-full rounded-xl" />
    </div>
  );
}
