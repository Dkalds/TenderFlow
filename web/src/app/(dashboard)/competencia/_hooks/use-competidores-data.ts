"use client";

/**
 * Las cuatro peticiones de Competidores y el estado local de la pantalla.
 *
 * Separado de `use-competidores-view.ts` a propósito: aquel agrega series sobre
 * datos ya descargados y se puede probar sin red; este es el que habla con la
 * API. Mezclarlos obligaba a montar la pantalla entera para tocar cualquiera de
 * los dos.
 *
 * Las dos peticiones del dossier viajan con el mismo ámbito que la tabla
 * (`useFilteredQuery`), y con `empresa_ids` cuando el competidor es una
 * agrupación: el dossier agrega todas las identidades del grupo, y el usuario
 * nunca elige cuál abrir.
 */

import { useCallback, useMemo, useState } from "react";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useSortToggle } from "@/hooks/use-sort-toggle";
import { useEmpresasWatchlist, useToggleEmpresaWatch } from "@/hooks/use-empresas-watchlist";
import { useFilters } from "@/lib/filters";
import { toggleValue } from "@/lib/chart-interaction";
import type { ScatterPoint } from "@/components/charts/competitors-charts";
import type { CompanyAwardsData, CompanyProfileData } from "@/components/competitors/company-profile-types";

import {
  drillDownExtraParams,
  drillDownIds,
  toggleCompareSelection,
} from "./competidores-tabla";
import type { BajaItem, Competitor, HeatmapEntry, SortKey } from "./competidores-types";
import { useCompetidoresView } from "./use-competidores-view";

export interface CompetitorsData {
  total_adjudicaciones: number;
  total_empresas?: number;
  importe_total?: number;
  hhi: number;
  pct_oferta_unica: number;
  /**
   * Qué porcentaje de las adjudicaciones trae el número de ofertantes.
   *
   * Es el denominador de `pct_oferta_unica`, y sin él ese porcentaje no
   * significa nada: `services/analytics/competitors.py` lo calcula solo sobre
   * las licitaciones que reportan el dato («cobertura parcial según fuente»,
   * dice su propio comentario). La API ya lo envía —`shared/dto.py`— y esta
   * pantalla no lo miraba: publicaba el porcentaje a secas mientras `/resumen`,
   * un clic más allá, se abstenía de publicarlo por cobertura insuficiente.
   */
  cobertura_ofertas_pct?: number | null;
  pct_pyme: number;
  top_competidor: string;
  competitors: Competitor[];
  scatter_data?: ScatterPoint[];
  heatmap_ccaa?: HeatmapEntry[];
  estacionalidad?: { mes: number; count: number; importe: number }[];
}

export function useCompetidoresData() {
  const { data, isLoading, error } = useFilteredQuery<CompetitorsData>(
    ["analytics", "competitors"],
    "/api/v1/analytics/competitors",
    { staleTime: 5 * 60 * 1000 },
    { limit: "100" },
  );

  // Ranking de bajas por empresa (quién oferta más agresivo). Honra ccaa global
  // vía useFilteredQuery; el endpoint ignora el resto de filtros.
  const { data: bajasData } = useFilteredQuery<{ items: BajaItem[] }>(
    ["competitive", "bajas-empresa"],
    "/api/v1/competitive/bajas",
    { staleTime: 5 * 60 * 1000 },
    { group_by: "empresa", min_contratos: "5", limit: "15" },
  );

  const { watchedIds } = useEmpresasWatchlist();
  const toggleWatch = useToggleEmpresaWatch();

  const [search, setSearch] = useState("");
  const { ccaas, setCcaas } = useFilters();
  const activeCcaa = useMemo(() => new Set(ccaas), [ccaas]);
  const toggleCcaa = useCallback(
    (ccaa: string) => setCcaas(toggleValue(ccaa, ccaas)),
    [ccaas, setCcaas],
  );
  const { sortKey, sortDir, toggleSort } = useSortToggle<SortKey>("count");
  const [selectedCompanies, setSelectedCompanies] = useState<string[]>([]);
  const [drillDownCompany, setDrillDownCompany] = useState<Competitor | null>(null);

  // Grupo de identidades del maestro que representan al mismo competidor
  // analítico (mismo nombre/NIF conectado, aún sin fusionar).
  const drillDownGroupIds = useMemo(() => drillDownIds(drillDownCompany), [drillDownCompany]);
  const drillDownCompanyId = drillDownGroupIds[0];
  const drillDownParams = useMemo(
    () => drillDownExtraParams(drillDownGroupIds),
    [drillDownGroupIds],
  );

  const { data: drillDownProfile, isLoading: isLoadingDrillDownProfile } =
    useFilteredQuery<CompanyProfileData>(
      ["competitive-company-profile", String(drillDownCompanyId ?? "none"), drillDownGroupIds.join(",")],
      `/api/v1/competitive/empresas/${drillDownCompanyId ?? 0}/perfil`,
      { enabled: drillDownCompanyId != null, staleTime: 5 * 60 * 1000 },
      drillDownParams,
    );

  const { data: drillDownAwards, isLoading: isLoadingDrillDownAwards } =
    useFilteredQuery<CompanyAwardsData>(
      [
        "competitive-company-awards-preview",
        String(drillDownCompanyId ?? "none"),
        drillDownGroupIds.join(","),
      ],
      `/api/v1/competitive/empresas/${drillDownCompanyId ?? 0}/adjudicaciones`,
      { enabled: drillDownCompanyId != null, staleTime: 5 * 60 * 1000 },
      { limit: "5", offset: "0", sort: "fecha_desc", ...drillDownParams },
    );

  const onToggleCompare = useCallback(
    (nombre: string) => setSelectedCompanies((prev) => toggleCompareSelection(prev, nombre)),
    [],
  );

  // Todas las series de la pantalla (búsqueda, orden, tarta, barras, dispersión,
  // mapa de calor, radar, treemap, posicionamiento, estacionalidad y ranking de
  // bajas) viven en `_hooks/competidores-series.ts` como funciones puras.
  const series = useCompetidoresView({
    competitors: data?.competitors,
    scatterData: data?.scatter_data,
    heatmapCcaa: data?.heatmap_ccaa,
    estacionalidad: data?.estacionalidad,
    importeTotal: data?.importe_total,
    bajas: bajasData?.items,
    search,
    sortKey,
    sortDir,
    selectedCompanies,
  });

  return {
    data,
    isLoading,
    error,
    series,
    search,
    setSearch,
    activeCcaa,
    toggleCcaa,
    sortKey,
    sortDir,
    toggleSort,
    selectedCompanies,
    onToggleCompare,
    drillDownCompany,
    setDrillDownCompany,
    drillDownCompanyId,
    drillDownGroupIds,
    drillDownProfile,
    drillDownAwards,
    isLoadingDrillDownProfile,
    isLoadingDrillDownAwards,
    watchedIds,
    toggleWatch,
  };
}
