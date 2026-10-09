"use client";

/**
 * La petición de UTE y el estado local de la pantalla.
 *
 * Separado de `utes-series.ts` y `utes-red.ts` a propósito: aquéllos dan forma
 * a datos ya descargados y se comprueban sin red; éste habla con la API,
 * guarda lo que el usuario ha elegido —una empresa de la red y el texto del
 * buscador— y memoiza las series.
 *
 * La respuesta se tipa desde el esquema generado (`Schemas["UTEResult"]`) y no
 * con una `interface` propia: una escrita a mano nombraba el mes `periodo` y
 * los contratos `count` cuando la API manda `period` y `contratos`, y compiló
 * así mientras la evolución llegaba vacía a pantalla.
 */

import { useMemo, useState } from "react";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

import { disponerRed, marcarSeleccion } from "./utes-red";
import { filasAlianzas, filasMariposa, serieEvolucion } from "./utes-series";

export function useUtesData() {
  const { data, isLoading, error, refetch } = useFilteredQuery<Schemas["UTEResult"]>(
    ["analytics", "utes"],
    "/api/v1/analytics/utes",
    // El error lo pinta la vista en línea (PanelError): sin toast además.
    { staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
  );

  const [busqueda, setBusqueda] = useState("");
  const [empresaElegida, setEmpresaElegida] = useState<string | null>(null);

  const pares = data?.socios_frecuentes;
  const utes = data?.top_miembros;
  const meses = data?.evolucion;

  const disposicion = useMemo(() => disponerRed(pares ?? []), [pares]);
  // La red decide si la elegida sigue vigente: al cambiar el ámbito puede
  // quedarse sin pares, y entonces la lista vuelve a ser la de todos.
  const red = useMemo(() => marcarSeleccion(disposicion, empresaElegida), [disposicion, empresaElegida]);
  const alianzas = useMemo(() => filasAlianzas(pares, red.elegida), [pares, red.elegida]);
  const mariposa = useMemo(() => filasMariposa(utes, busqueda), [utes, busqueda]);
  const evolucion = useMemo(() => serieEvolucion(meses), [meses]);

  return {
    data,
    isLoading,
    error,
    /** El «Reintentar» del error. */
    refetch: () => void refetch(),
    red,
    alianzas,
    /** Elige una empresa; pulsar la ya elegida —o pasar `null`— la suelta. */
    elegirEmpresa: (empresa: string | null) =>
      setEmpresaElegida((actual) => (empresa == null || empresa === actual ? null : empresa)),
    mariposa,
    busqueda,
    setBusqueda,
    evolucion,
  };
}
