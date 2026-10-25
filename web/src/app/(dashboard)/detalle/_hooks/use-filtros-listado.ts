"use client";

import { useMemo } from "react";
import { useFilterParams } from "@/lib/filters";
import { useCierreRecorte, type CierreRecorte } from "./use-cierre-recorte";
import { useEtiquetaDelListado } from "./use-etiqueta-listado";

/**
 * Los filtros con los que /detalle pide su listado: el ámbito global de la URL,
 * el recorte por ventana de cierre (`?cierre_desde=`/`?cierre_hasta=`) y la
 * etiqueta.
 *
 * El recorte se suma al ámbito en vez de sustituirlo: el deep-link de una
 * tarjeta de /resumen llega con la ventana de cierre y con los chips de ámbito
 * que hubiera puestos, y la tabla tiene que respetar los dos. La etiqueta
 * también filtra en servidor (F1.6, CU-28).
 *
 * Es un hook aparte para que el prefetch en servidor (`_lib/prefetch.ts`) y su
 * test de paridad partan de la misma composición que la pantalla.
 */
export function useFiltrosDelListado(): {
  cierre: CierreRecorte;
  etiqueta: ReturnType<typeof useEtiquetaDelListado>;
  queryFilters: Record<string, string>;
} {
  const filterParams = useFilterParams();
  const cierre = useCierreRecorte();
  const etiqueta = useEtiquetaDelListado();
  const queryFilters = useMemo(
    () => ({ ...filterParams, ...cierre.params, ...etiqueta.params }),
    [filterParams, cierre.params, etiqueta.params],
  );
  return { cierre, etiqueta, queryFilters };
}
