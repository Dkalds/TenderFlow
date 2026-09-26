import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de la ficha de una oportunidad.
 *
 * Lo pintan el `loading.tsx` de ruta y `page.tsx` mientras `usePursuit` está
 * pendiente: la página es cliente y pide su dato al montarse, así que lo
 * primero que enseña después del esqueleto de ruta es su propio estado
 * pendiente. Con un solo componente para los dos el relevo no se ve; con una
 * silueta de la ficha completa en la ruta, el usuario vería una forma, luego
 * otra más pobre y luego la ficha.
 */
export function FichaEsqueleto() {
  return (
    <div data-slot="ficha-esqueleto" className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Skeleton className="h-24 w-full rounded-xl" />
      <Skeleton className="h-[360px] w-full rounded-xl" />
    </div>
  );
}
