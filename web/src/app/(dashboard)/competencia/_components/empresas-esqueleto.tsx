import { Skeleton } from "@/components/ui/skeleton";

/**
 * Lo que pintan Competencia › Empresas y › Revisión mientras llega su chunk o
 * su ruta: la columna del maestro y la ficha al lado, con las cotas de la
 * pantalla (`bleed`, sin relleno del cuerpo).
 *
 * Es el cuerpo del esqueleto que tenía la ruta `/empresas`. Lo comparten el
 * `loading` de `next/dynamic` de la página y el `loading.tsx` de la ruta, para
 * que la vista aparezca donde estaba su esqueleto y no salte al llegar.
 */
export function EmpresasEsqueleto() {
  return (
    <div className="flex h-full min-h-0" data-slot="empresas-esqueleto">
      <div className="border-border/60 flex w-[560px] flex-none flex-col gap-2 border-r p-4">
        <Skeleton className="mb-1 h-8 w-full rounded-md" />
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-8 w-full rounded-md" />
        ))}
      </div>
      <div className="bg-card flex min-w-0 flex-1 flex-col gap-3 p-5">
        {[72, 64, 120, 140].map((height) => (
          <Skeleton key={height} className="w-full rounded-xl" style={{ height }} />
        ))}
      </div>
    </div>
  );
}
