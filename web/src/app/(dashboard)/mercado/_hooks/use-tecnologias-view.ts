"use client";

/**
 * Datos y series de la vista Tecnologías.
 *
 * Las tres peticiones (agregado, detalle de la tecnología elegida y top por
 * score) y todas las transformaciones de presentación viven aquí. Ninguna
 * inventa analítica: pivotan, ordenan y recortan lo que el backend ya calculó
 * sobre el dataset completo (ADR-014). El único agregado local es el bucket
 * «Otros» del donut y las sumas por mes/CCAA de los cruces, que el endpoint
 * entrega ya desglosados y aquí sólo se giran de filas a columnas.
 */

import { useMemo, useState } from "react";

import { useFilteredQuery } from "@/hooks/use-filtered-query";

export interface TecnologiaItem {
  tecnologia: string;
  count: number;
  importe: number;
  importe_medio: number;
  pct: number;
  pct_adjudicado: number;
}

export interface CrossOrganoItem {
  organo: string;
  tecnologia: string;
  count: number;
}

export interface CrossGeoItem {
  ccaa: string;
  tecnologia: string;
  count: number;
}

export interface EvolucionItem {
  mes: string;
  tecnologia: string;
  count: number;
  importe: number;
}

export interface TecnologiasResponse {
  tecnologias: TecnologiaItem[];
  sin_clasificar: number;
  total?: number;
  n_tecnologias: number;
  tecnologia_lider: string | null;
  lider_count: number;
  importe_medio_global: number;
  tasa_adjudicacion_media: number;
  cross_organo: CrossOrganoItem[];
  cross_geo: CrossGeoItem[];
  evolucion_mensual: EvolucionItem[];
}

export interface DetalleItem {
  id_externo: string;
  titulo: string | null;
  organo_contratacion: string | null;
  importe: number | null;
  estado: string | null;
  ccaa: string | null;
  fecha_publicacion: string | null;
}

export interface DetalleResponse {
  tecnologia: string;
  n: number;
  importe_total: number;
  importe_medio: number;
  items: DetalleItem[];
}

export interface ScoredItem {
  id: string;
  titulo: string;
  importe: number;
  score: number;
  organo_contratacion?: string;
}

interface ScoringResponse {
  opportunities: ScoredItem[];
}

/** Fila de cualquiera de los dos gráficos de barras: el ítem más su color. */
export type BarItem = TecnologiaItem & { _color: string };

/** Matriz tecnología × órgano ya ordenada por totales. */
export interface HeatmapMatrix {
  techs: string[];
  organos: string[];
  cell: Map<string, number>;
  maxVal: number;
}

export type TrendMetric = "count" | "importe";

/**
 * Sequential scale on the primary accent — used to color the "volumen" bars by importe.
 * Stays within the token palette so charts feel cohesive across pages.
 */
function primaryScale(t: number): string {
  const alpha = 0.25 + Math.min(Math.max(t, 0), 1) * 0.7;
  return `hsl(var(--primary) / ${alpha})`;
}

/**
 * Sequential scale on the secondary chart accent (--chart-2) — used for the
 * "importe" bars so the two stacks read as related but distinct.
 */
function accentScale(t: number): string {
  const alpha = 0.25 + Math.min(Math.max(t, 0), 1) * 0.7;
  return `hsl(var(--chart-2) / ${alpha})`;
}

export function useTecnologiasView() {
  const [filter, setFilter] = useState("");
  const [selectedTech, setSelectedTech] = useState<string>("");
  const [trendMetric, setTrendMetric] = useState<TrendMetric>("count");

  const { data, isLoading, error } = useFilteredQuery<TecnologiasResponse>(
    ["analytics", "tecnologias"],
    "/api/v1/analytics/tecnologias",
    { staleTime: 5 * 60 * 1000 },
  );

  // Per-technology detail (only when a technology is selected)
  const { data: detalle, isLoading: detalleLoading } = useFilteredQuery<DetalleResponse>(
    ["analytics", "tecnologias", "detail", selectedTech],
    "/api/v1/analytics/tecnologias/detail",
    { enabled: !!selectedTech, staleTime: 5 * 60 * 1000 },
    selectedTech ? { tecnologia: selectedTech } : undefined,
  );

  // Top scored opportunities
  const { data: scoringData } = useFilteredQuery<ScoringResponse>(
    ["analytics", "scoring", "top20"],
    "/api/v1/analytics/scoring",
    { staleTime: 5 * 60 * 1000 },
    { limit: "20" },
  );

  const items = useMemo(() => data?.tecnologias ?? [], [data]);

  const donutData = useMemo(() => {
    const sorted = [...items].sort((a, b) => b.count - a.count);
    if (sorted.length <= 10) return sorted;
    const top = sorted.slice(0, 9);
    const rest = sorted.slice(9);
    return [
      ...top,
      {
        tecnologia: "Otros",
        count: rest.reduce((s, i) => s + i.count, 0),
        importe: rest.reduce((s, i) => s + i.importe, 0),
        importe_medio: 0,
        pct: rest.reduce((s, i) => s + i.pct, 0),
        pct_adjudicado: 0,
      },
    ];
  }, [items]);

  // Volumen (nº licitaciones), colored by importe
  const volumeBar = useMemo<BarItem[]>(() => {
    const maxImp = Math.max(1, ...items.map((i) => i.importe));
    return [...items]
      .sort((a, b) => b.count - a.count)
      .slice(0, 15)
      .map((i) => ({ ...i, _color: primaryScale(i.importe / maxImp) }))
      .reverse();
  }, [items]);

  // Importe, colored by nº licitaciones
  const importeBar = useMemo<BarItem[]>(() => {
    const withImporte = items.filter((i) => i.importe > 0);
    const maxN = Math.max(1, ...withImporte.map((i) => i.count));
    return [...withImporte]
      .sort((a, b) => b.importe - a.importe)
      .slice(0, 15)
      .map((i) => ({ ...i, _color: accentScale(i.count / maxN) }))
      .reverse();
  }, [items]);

  const filteredItems = useMemo(() => {
    if (!filter) return items;
    const q = filter.toLowerCase();
    return items.filter((i) => i.tecnologia.toLowerCase().includes(q));
  }, [items, filter]);

  // Monthly evolution split by technology (stacked area)
  const evol = useMemo(() => data?.evolucion_mensual ?? [], [data]);
  const evolTechs = useMemo(() => {
    const totals = new Map<string, number>();
    for (const e of evol) totals.set(e.tecnologia, (totals.get(e.tecnologia) ?? 0) + e.count);
    return [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([t]) => t);
  }, [evol]);
  const evolData = useMemo(() => {
    const byMes = new Map<string, Record<string, number | string>>();
    for (const e of evol) {
      if (!byMes.has(e.mes)) byMes.set(e.mes, { mes: e.mes });
      const row = byMes.get(e.mes)!;
      const prev = (row[e.tecnologia] as number) ?? 0;
      row[e.tecnologia] = prev + (trendMetric === "importe" ? e.importe : e.count);
    }
    return [...byMes.values()].sort((a, b) => String(a.mes).localeCompare(String(b.mes)));
  }, [evol, trendMetric]);

  // Real tecnologia x organo heatmap (replaces the previous synthetic matrix)
  const heatmap = useMemo<HeatmapMatrix | null>(() => {
    const cross = data?.cross_organo ?? [];
    if (cross.length === 0) return null;
    const techTotals = new Map<string, number>();
    const orgTotals = new Map<string, number>();
    for (const c of cross) {
      techTotals.set(c.tecnologia, (techTotals.get(c.tecnologia) ?? 0) + c.count);
      orgTotals.set(c.organo, (orgTotals.get(c.organo) ?? 0) + c.count);
    }
    const techs = [...techTotals.entries()].sort((a, b) => b[1] - a[1]).map(([t]) => t);
    const organos = [...orgTotals.entries()].sort((a, b) => b[1] - a[1]).map(([o]) => o);
    const cell = new Map<string, number>();
    let maxVal = 0;
    for (const c of cross) {
      cell.set(`${c.tecnologia}||${c.organo}`, c.count);
      if (c.count > maxVal) maxVal = c.count;
    }
    return { techs, organos, cell, maxVal };
  }, [data]);

  // Geographic distribution by technology (grouped bar)
  const crossGeo = useMemo(() => data?.cross_geo ?? [], [data]);
  const geoTechs = useMemo(() => {
    const totals = new Map<string, number>();
    for (const c of crossGeo) totals.set(c.tecnologia, (totals.get(c.tecnologia) ?? 0) + c.count);
    return [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([t]) => t);
  }, [crossGeo]);
  const geoData = useMemo(() => {
    const byCcaa = new Map<string, Record<string, number | string>>();
    const ccaaTotals = new Map<string, number>();
    for (const c of crossGeo) {
      ccaaTotals.set(c.ccaa, (ccaaTotals.get(c.ccaa) ?? 0) + c.count);
      if (!byCcaa.has(c.ccaa)) byCcaa.set(c.ccaa, { ccaa: c.ccaa });
      byCcaa.get(c.ccaa)![c.tecnologia] = c.count;
    }
    return [...byCcaa.values()].sort(
      (a, b) => (ccaaTotals.get(String(b.ccaa)) ?? 0) - (ccaaTotals.get(String(a.ccaa)) ?? 0),
    );
  }, [crossGeo]);

  return {
    data,
    items,
    filteredItems,
    donutData,
    volumeBar,
    importeBar,
    evolData,
    evolTechs,
    heatmap,
    geoData,
    geoTechs,
    detalle,
    detalleLoading,
    scoredItems: scoringData?.opportunities ?? [],
    filter,
    setFilter,
    selectedTech,
    setSelectedTech,
    trendMetric,
    setTrendMetric,
    isLoading,
    error,
  };
}
