"use client";

/**
 * Datos y series de la vista Órganos.
 *
 * Dos peticiones con **el mismo ámbito**: el ranking y el drill-down del órgano
 * abierto. Que compartan filtros no es un detalle de implementación — el panel
 * lleva el nombre del órgano en la cabecera, y responder ahí con el histórico
 * completo mientras la tabla cuenta sólo las SAP es el mismo encabezado sobre
 * dos universos.
 */

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useDebounce } from "@/hooks/use-debounce";
import { foldText } from "@/lib/utils";

const TIPO_CONTRATO_LABEL: Record<string, string> = {
  "1": "Servicios",
  "2": "Suministros",
  "3": "Obras",
};

export interface OrganoItem {
  organo_contratacion: string;
  count: number;
  importe: number;
  pct: number;
  ccaa?: string;
}

export interface TreemapBreakdownItem {
  organo: string;
  tipo_contrato: string;
  importe: number;
}

export interface OrganosResponse {
  organos: OrganoItem[];
  total_organos: number;
  importe_total?: number;
  concentracion_top10?: number;
  treemap_breakdown?: TreemapBreakdownItem[];
}

export interface OrganoKpis {
  total_licitaciones: number;
  importe_total: number;
  importe_medio: number;
  pct_adjudicado: number;
  lead_time_medio: number | null;
  top_adjudicatario: string | null;
  top_adj_importe: number;
}

export interface TopScoredItem {
  id_externo: string;
  titulo: string | null;
  importe: number | null;
  score: number;
  ccaa?: string | null;
  estado?: string | null;
  estado_desc?: string | null;
  banda?: string | null;
  empresa?: string | null;
  baja_pct?: number | null;
  fecha_adjudicacion?: string | null;
  modulos_str?: string | null;
  url?: string | null;
  tipo_proyecto?: string | null;
  tipo_contrato_desc?: string | null;
  cpv_desc?: string | null;
}

export interface OrganoDetailResponse {
  kpis: OrganoKpis;
  top_adjudicatarios: { nombre: string; count: number; importe: number }[];
  estacionalidad: { mes_numero: number; count: number }[];
  top_scored: TopScoredItem[];
}

/** Nodo del treemap: jerárquico si el backend manda desglose, plano si no. */
export type OrganoTreemapNode =
  | { name: string; children: { name: string; size: number }[] }
  | { name: string; size: number };

export function useOrganosView() {
  const searchParams = useSearchParams();
  // Deep-link externo: `?organo_q=<órgano>` siembra el filtro local. `q`
  // pertenece al ámbito global y useFilteredQuery lo adjunta por separado.
  const [filter, setFilter] = useState(() => searchParams?.get("organo_q") ?? "");
  const [selectedOrgano, setSelectedOrgano] = useState<string | null>(null);

  // Búsqueda server-side (accent-insensitive): sin q el API devuelve solo el
  // top-50 por actividad, así que un órgano fuera de ese ranking jamás
  // aparecería filtrando solo en cliente.
  const debouncedFilter = useDebounce(filter, 300);
  const { data, isLoading, error } = useFilteredQuery<OrganosResponse>(
    ["analytics", "organos", debouncedFilter],
    "/api/v1/analytics/organos",
    { staleTime: 5 * 60 * 1000 },
    debouncedFilter ? { organo_q: debouncedFilter } : undefined,
  );

  // El drill-down viaja con el mismo ámbito que el ranking del que se abre.
  // Antes era un `fetch` desnudo sin un solo parámetro: entrando con
  // `?tecnologia=SAP`, la tabla contaba las licitaciones SAP del órgano y el
  // panel de al lado respondía con su histórico completo — dos universos, el
  // mismo encabezado. `useFilteredQuery` además mete los filtros en la key,
  // así que cambiar de ámbito refetchea en vez de servir el panel anterior.
  //
  // El último argumento (`isRealtime`) apaga `keepPreviousData` a propósito: el
  // panel lleva el nombre del órgano en la cabecera, y servir las cifras del
  // anterior mientras carga el nuevo es la misma mentira que este cambio viene
  // a quitar. Aquí se prefiere el esqueleto.
  const { data: detailData, isLoading: detailLoading } = useFilteredQuery<OrganoDetailResponse>(
    ["analytics", "organo-detail", selectedOrgano ?? ""],
    `/api/v1/analytics/organos/${encodeURIComponent(selectedOrgano ?? "")}`,
    { enabled: !!selectedOrgano, staleTime: 5 * 60 * 1000 },
    undefined,
    true,
  );

  const items = useMemo(() => data?.organos ?? [], [data]);

  const filteredItems = useMemo(() => {
    if (!filter) return items;
    const q = foldText(filter);
    return items.filter(
      (i) =>
        foldText(i.organo_contratacion).includes(q) ||
        (i.ccaa && foldText(i.ccaa).includes(q)),
    );
  }, [items, filter]);

  const maxCount = useMemo(
    () => (filteredItems.length > 0 ? Math.max(...filteredItems.map((i) => i.count)) : 1),
    [filteredItems],
  );

  const top20 = useMemo(() => filteredItems.slice(0, 20), [filteredItems]);

  const top15ByImporte = useMemo(
    () => [...filteredItems].sort((a, b) => b.importe - a.importe).slice(0, 15),
    [filteredItems],
  );

  // Hierarchical treemap: organo → tipo_contrato if backend provides breakdown
  const treemapData = useMemo<OrganoTreemapNode[]>(() => {
    const breakdown = data?.treemap_breakdown;
    if (breakdown && breakdown.length > 0) {
      // Filter by local search if active
      const relevant = filter
        ? breakdown.filter((b) => foldText(b.organo).includes(foldText(filter)))
        : breakdown;
      const map = new Map<string, { name: string; children: { name: string; size: number }[] }>();
      for (const item of relevant) {
        const key = item.organo;
        if (!map.has(key)) {
          map.set(key, { name: key.slice(0, 40), children: [] });
        }
        const label = TIPO_CONTRATO_LABEL[item.tipo_contrato] ?? item.tipo_contrato ?? "Otro";
        map.get(key)!.children.push({ name: label, size: item.importe });
      }
      return Array.from(map.values());
    }
    // Fallback: flat treemap
    return filteredItems
      .filter((i) => i.importe > 0)
      .slice(0, 30)
      .map((i) => ({ name: i.organo_contratacion, size: i.importe }));
  }, [data, filteredItems, filter]);

  return {
    data,
    items,
    filteredItems,
    maxCount,
    top20,
    top15ByImporte,
    treemapData,
    // Totales reales del backend (sobre TODO el dataset), no la suma del top-50
    // que devuelve `items`: antes "Concentración Top 10" se inflaba (denominador
    // = top-50) e "Importe Total" se subestimaba (ignoraba órganos fuera del
    // top-50). `?? null` y no `?? 0`: un campo que el backend no manda no es un
    // cero. Un "0 %" de concentración se lee como "mercado perfectamente
    // repartido" y un "0 €" de importe total como "no se licitó nada" — dos
    // afirmaciones que el dataset no hace. La tarjeta se abstiene con
    // `valorOEmpty`.
    top10Concentration: data?.concentracion_top10 ?? null,
    totalImporte: data?.importe_total ?? null,
    topOrgano: items.length > 0 ? items[0].organo_contratacion : "-",
    filter,
    setFilter,
    selectedOrgano,
    setSelectedOrgano,
    detailData,
    detailLoading,
    isLoading,
    error,
  };
}
