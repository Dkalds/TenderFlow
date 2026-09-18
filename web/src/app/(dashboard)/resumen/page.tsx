import { PrefetchServidor } from "@/components/prefetch-servidor";
import { filterParamsFromSearch, type SearchParamsServidor } from "@/lib/filter-params";
import { consultasResumen } from "./_lib/prefetch";
import { ResumenView } from "./_components/resumen-view";

/**
 * Resumen en servidor: pide el dato de la primera pantalla mientras renderiza
 * y se lo entrega hidratado a `ResumenView`, que es la pantalla de siempre.
 *
 * Antes esta ruta era `"use client"` entera: el HTML llegaba con esqueletos y
 * las peticiones salían después de hidratar. El ámbito se lee de la URL con la
 * misma derivación que `useFilterParams`, así que un enlace compartido con
 * `?tecnologia=SAP` llega ya con sus cifras. Si la API tarda más que el
 * presupuesto del prefetch, la pantalla se comporta exactamente como antes.
 */
export default async function ResumenPage({
  searchParams,
}: {
  searchParams: Promise<SearchParamsServidor>;
}) {
  const filtros = filterParamsFromSearch(await searchParams);
  return (
    <PrefetchServidor consultas={consultasResumen(filtros)}>
      <ResumenView />
    </PrefetchServidor>
  );
}
