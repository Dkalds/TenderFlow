"use client";

/**
 * Agregador de las series de Competidores.
 *
 * La vista —`_components/competidores-view.tsx`, que hasta 2026-09 vivió en
 * `competidores/page.tsx`— traía once `useMemo` encadenados dentro del
 * componente. Aquí quedan memoizados en un solo sitio sobre los datos ya
 * descargados; las reglas de cada serie viven en `competidores-series.ts` y las
 * de la tabla en `competidores-tabla.ts`, ambas como funciones puras.
 *
 * No hay fetch: eso es `use-competidores-data.ts`.
 */

import { useMemo } from "react";

import {
  buildBarData,
  buildEstacionalidad,
  buildHeatmap,
  buildPieData,
  buildPositioningData,
  buildRadarData,
  buildScatterTop5,
  buildTreemapData,
  sortBajas,
  type BajasModel,
  type EstacionalidadPoint,
  type HeatmapModel,
  type PieSlice,
  type PositioningPoint,
  type RadarModel,
  type TreemapNode,
} from "./competidores-series";
import { filterBySearch, sortCompetitors } from "./competidores-tabla";
import type { BajaItem, Competitor, HeatmapEntry, Searchable, SortKey } from "./competidores-types";

export interface CompetidoresViewInput<S extends Searchable> {
  competitors: Competitor[] | undefined;
  scatterData: S[] | undefined;
  heatmapCcaa: HeatmapEntry[] | undefined;
  estacionalidad: { mes: number; count: number; importe: number }[] | undefined;
  importeTotal: number | undefined;
  bajas: BajaItem[] | undefined;
  search: string;
  sortKey: SortKey;
  sortDir: "asc" | "desc";
  selectedCompanies: string[];
}

export interface CompetidoresView<S extends Searchable> {
  filteredCompetitors: Competitor[];
  filteredSorted: Competitor[];
  pieData: PieSlice[];
  barData: Competitor[];
  scatterData: S[];
  scatterTop5: Set<string>;
  heatmapData: HeatmapModel;
  radarData: RadarModel | null;
  treemapData: TreemapNode[];
  positioningData: PositioningPoint[];
  estacionalidadData: EstacionalidadPoint[];
  bajasSorted: BajasModel;
}

/** Todas las series de la pantalla, memoizadas sobre los datos ya descargados. */
export function useCompetidoresView<S extends Searchable>({
  competitors,
  scatterData,
  heatmapCcaa,
  estacionalidad,
  importeTotal,
  bajas,
  search,
  sortKey,
  sortDir,
  selectedCompanies,
}: CompetidoresViewInput<S>): CompetidoresView<S> {
  const filteredCompetitors = useMemo(
    () => filterBySearch(competitors ?? [], search),
    [competitors, search],
  );

  const filteredSorted = useMemo(
    () => sortCompetitors(filteredCompetitors, sortKey, sortDir),
    [filteredCompetitors, sortKey, sortDir],
  );

  const pieData = useMemo(
    () => buildPieData(filteredCompetitors, search, importeTotal),
    [filteredCompetitors, search, importeTotal],
  );

  const barData = useMemo(() => buildBarData(filteredCompetitors), [filteredCompetitors]);

  const filteredScatter = useMemo(
    () => filterBySearch(scatterData ?? [], search),
    [scatterData, search],
  );

  const scatterTop5 = useMemo(() => buildScatterTop5(competitors), [competitors]);

  const heatmapData = useMemo(() => buildHeatmap(heatmapCcaa, search), [heatmapCcaa, search]);

  const radarData = useMemo(
    () => buildRadarData(selectedCompanies, competitors),
    [selectedCompanies, competitors],
  );

  const treemapData = useMemo(
    () => buildTreemapData(filteredCompetitors),
    [filteredCompetitors],
  );

  const positioningData = useMemo(
    () => buildPositioningData(filteredCompetitors),
    [filteredCompetitors],
  );

  const estacionalidadData = useMemo(
    () => buildEstacionalidad(estacionalidad),
    [estacionalidad],
  );

  const bajasSorted = useMemo(() => sortBajas(bajas), [bajas]);

  return {
    filteredCompetitors,
    filteredSorted,
    pieData,
    barData,
    scatterData: filteredScatter,
    scatterTop5,
    heatmapData,
    radarData,
    treemapData,
    positioningData,
    estacionalidadData,
    bajasSorted,
  };
}
