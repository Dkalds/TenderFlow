"use client";

/**
 * La petición de UTEs y el estado local de la pantalla.
 *
 * Separado de `utes-series.ts` a propósito: aquél da forma a datos ya
 * descargados y se puede comprobar sin red; éste es el que habla con la API y
 * memoiza el resultado. Mismo reparto que en Competidores.
 */

import { useMemo, useState } from "react";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

import {
  buildComparativaRows,
  buildMemberDistribution,
  buildTopMiembrosPorImporte,
  filterMiembros,
} from "./utes-series";
import type { UTEsData } from "./utes-types";

export function useUtesData() {
  const { data, isLoading, error, refetch } = useFilteredQuery<UTEsData>(
    ["analytics", "utes"],
    "/api/v1/analytics/utes",
    // El error lo pinta la vista en línea (PanelError): sin toast además.
    { staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
  );

  const [memberSearch, setMemberSearch] = useState("");

  const comparativa = data?.tabla_comparativa;
  const miembros = data?.top_miembros;

  const comparativaRows = useMemo(() => buildComparativaRows(comparativa), [comparativa]);

  const filteredMiembros = useMemo(
    () => filterMiembros(miembros, memberSearch),
    [miembros, memberSearch],
  );

  const memberDistribution = useMemo(() => buildMemberDistribution(miembros), [miembros]);

  const topMiembrosByImporte = useMemo(
    () => buildTopMiembrosPorImporte(miembros),
    [miembros],
  );

  return {
    data,
    isLoading,
    error,
    /** El «Reintentar» del error. */
    refetch: () => void refetch(),
    memberSearch,
    setMemberSearch,
    comparativaRows,
    filteredMiembros,
    memberDistribution,
    topMiembrosByImporte,
  };
}
