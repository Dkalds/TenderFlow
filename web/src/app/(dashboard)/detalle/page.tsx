import { PrefetchServidor } from "@/components/prefetch-servidor";
import type { SearchParamsServidor } from "@/lib/filter-params";
import { consultasDetalle } from "./_lib/prefetch";
import { DetalleView } from "./_components/detalle-view";

/**
 * Detalle en servidor: pide la primera página del listado (y la ficha, si la
 * URL abre una) mientras renderiza y se la entrega hidratada a `DetalleView`,
 * que es la pantalla cliente de siempre.
 *
 * Antes la tabla llegaba con esqueletos y el listado salía después de
 * hidratar. Ahora un enlace compartido —con su ámbito, su ventana de cierre o
 * su `?lic=`— llega con sus filas. Si la API tarda más que el presupuesto del
 * prefetch, la pantalla se comporta exactamente como antes (S7.1,
 * `web/AGENTS.md`).
 */
export default async function DetallePage({
  searchParams,
}: {
  searchParams: Promise<SearchParamsServidor>;
}) {
  return (
    <PrefetchServidor consultas={consultasDetalle(await searchParams)}>
      <DetalleView />
    </PrefetchServidor>
  );
}
