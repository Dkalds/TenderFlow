"use client";

/**
 * Datos, ordenación y selección de la vista Geografía.
 *
 * El reparto por CCAA y por provincia lo agrega el backend sobre el dataset
 * completo y respetando los filtros globales (vía `useFilteredQuery`); aquí
 * sólo se ordena, se recorta el bucket «Otros» del donut y se calcula la
 * concentración del top 3 sobre el total de la misma respuesta (ADR-014: el
 * denominador es el universo que devolvió el endpoint, no una muestra).
 *
 * El filtro por CCAA no es estado local: vive en la URL a través de
 * `useFilters`, que es lo que hace que marcar una CCAA en el mapa siga
 * aplicándose al cambiar de vista dentro del espacio Mercado.
 */

import { useMemo, useState } from "react";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { toggleValue } from "@/lib/chart-interaction";
import { useFilters } from "@/lib/filters";

// Las formas salen del esquema generado (`useFilteredQuery` las deriva de la ruta).
export type GeoItem = Schemas["GeoEntry"];
export type ProvinciaItem = Schemas["ProvinciaEntry"];

export type SortKey = "ccaa" | "count" | "importe" | "pct";
export type SortDir = "asc" | "desc";
export type ProvSortKey = "provincia" | "count" | "importe";
export type MapMetric = "count" | "importe";

export function useGeografiaView() {
  const [sortKey, setSortKey] = useState<SortKey>("count");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [provSortKey, setProvSortKey] = useState<ProvSortKey>("count");
  const [provSortDir, setProvSortDir] = useState<SortDir>("desc");
  const [mapMetric, setMapMetric] = useState<MapMetric>("count");

  const { ccaas, setCcaas } = useFilters();
  const activeCcaa = useMemo(() => new Set(ccaas), [ccaas]);
  const toggleCcaa = (ccaa: string) => setCcaas(toggleValue(ccaa, ccaas));

  const { data, isLoading, error, refetch } = useFilteredQuery(
    ["analytics", "geography"],
    "/api/v1/analytics/geography",
    // El error lo pinta la vista en línea (PanelError): sin toast además.
    { staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
  );

  const items = useMemo(() => data?.by_ccaa ?? [], [data]);

  // Lo agregado viene del backend (ADR-014); aquí solo se elige el máximo.
  // Antes el «mayor importe medio» dividía entre todas las licitaciones, también
  // las que no publican importe, y bajaba a quien más las publica sin él.
  const topCcaa = data?.ccaa_mas_activa ?? "-";
  // Sin comunidades no hay concentración: el `0.0` por defecto no es un dato.
  const top3Concentration = data && items.length > 0 ? data.concentracion_top3 : null;
  const ccaaMayorTicket = useMemo(() => {
    let mejor: { ccaa: string; medio: number } | null = null;
    for (const item of items) {
      if (item.importe_medio == null) continue;
      if (!mejor || item.importe_medio > mejor.medio) mejor = { ccaa: item.ccaa, medio: item.importe_medio };
    }
    return mejor?.ccaa ?? "-";
  }, [items]);

  const mapData = useMemo(
    () => items.map((i) => ({ ccaa: i.ccaa, value: i[mapMetric] })),
    [items, mapMetric],
  );

  const barData = useMemo(
    () => [...items].sort((a, b) => b.count - a.count),
    [items],
  );

  const pieData = useMemo(() => {
    const sorted = [...items].sort((a, b) => b.importe - a.importe);
    if (sorted.length <= 10) return sorted;
    const top = sorted.slice(0, 9);
    const rest = sorted.slice(9);
    const otherImporte = rest.reduce((s, i) => s + i.importe, 0);
    return [
      ...top,
      { ccaa: "Otros", count: 0, importe: otherImporte, pct: 0 },
    ];
  }, [items]);

  const sortedItems = useMemo(() => {
    const sorted = [...items];
    sorted.sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (typeof aVal === "string" && typeof bVal === "string") {
        return sortDir === "asc"
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }
      return sortDir === "asc"
        ? (aVal as number) - (bVal as number)
        : (bVal as number) - (aVal as number);
    });
    return sorted;
  }, [items, sortKey, sortDir]);

  // Provincias agregadas en backend sobre el dataset completo y respetando los
  // filtros globales (vía useFilteredQuery), no un sample cliente de limit=500.
  const provinciaData = useMemo(() => data?.by_provincia ?? [], [data]);

  const sortedProvincias = useMemo(() => {
    const sorted = [...provinciaData];
    sorted.sort((a, b) => {
      if (provSortKey === "provincia") {
        return provSortDir === "asc"
          ? a.provincia.localeCompare(b.provincia)
          : b.provincia.localeCompare(a.provincia);
      }
      const aVal = a[provSortKey] as number;
      const bVal = b[provSortKey] as number;
      return provSortDir === "asc" ? aVal - bVal : bVal - aVal;
    });
    return sorted;
  }, [provinciaData, provSortKey, provSortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  function toggleProvSort(key: ProvSortKey) {
    if (provSortKey === key) {
      setProvSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setProvSortKey(key);
      setProvSortDir("desc");
    }
  }

  return {
    items,
    topCcaa,
    top3Concentration,
    ccaaMayorTicket,
    mapData,
    mapMetric,
    setMapMetric,
    barData,
    pieData,
    sortedItems,
    sortKey,
    sortDir,
    toggleSort,
    sortedProvincias,
    provSortKey,
    provSortDir,
    toggleProvSort,
    activeCcaa,
    toggleCcaa,
    isLoading,
    error,
    /** El «Reintentar» del error. */
    refetch: () => void refetch(),
  };
}
