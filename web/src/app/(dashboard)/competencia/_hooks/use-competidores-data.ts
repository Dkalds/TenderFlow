"use client";

/**
 * Las peticiones de Competidores y el estado local de la pantalla.
 *
 * Separado de `use-competidores-view.ts` a propósito: aquel agrega series sobre
 * datos ya descargados y se puede probar sin red; este es el que habla con la
 * API. Mezclarlos obligaba a montar la pantalla entera para tocar cualquiera de
 * los dos.
 *
 * La petición del perfil viaja con el mismo ámbito que el ranking
 * (`useFilteredQuery`), y con `empresa_ids` cuando el competidor es una
 * agrupación: el perfil agrega todas las identidades del grupo, y el usuario
 * nunca elige cuál abrir.
 */

import { useCallback, useMemo, useState } from "react";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { useSortToggle } from "@/hooks/use-sort-toggle";
import { useFilters } from "@/lib/filters";
import { toggleValue } from "@/lib/chart-interaction";
import type { CompanyProfileData } from "@/components/competitors/company-profile-types";

import { drillDownExtraParams, drillDownIds } from "./competidores-tabla";
import type { CompetitorsData, Lente, Metrica, SortKey } from "./competidores-types";
import { useCompetidoresView } from "./use-competidores-view";
import { useMovimientosVigiladas } from "./use-vigilados";
import { idsVigiladas } from "./vigilados";

export function useCompetidoresData() {
  const { data, isLoading, error, refetch } = useFilteredQuery<CompetitorsData>(
    ["analytics", "competitors"],
    "/api/v1/analytics/competitors",
    // El error lo pinta la vista en línea (PanelError): sin toast además.
    { staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
    { limit: "100" },
  );

  const { data: movimientos } = useMovimientosVigiladas();
  const vigiladas = useMemo(() => idsVigiladas(movimientos), [movimientos]);

  const [search, setSearch] = useState("");
  const [metrica, setMetrica] = useState<Metrica>("importe");
  const [lente, setLente] = useState<Lente>("precio");
  const { ccaas, setCcaas } = useFilters();
  const activeCcaa = useMemo(() => new Set(ccaas), [ccaas]);
  const toggleCcaa = useCallback(
    (ccaa: string) => setCcaas(toggleValue(ccaa, ccaas)),
    [ccaas, setCcaas],
  );
  const { sortKey, sortDir, toggleSort } = useSortToggle<SortKey>("count");

  const [seleccion, setSeleccion] = useState<string | null>(null);
  // El perfil arranca abierto con la primera del ranking; cerrarlo es una
  // decisión aparte de «ninguna elegida», porque sin ella el cierre volvería a
  // abrir la primera.
  const [perfilCerrado, setPerfilCerrado] = useState(false);
  const [rival, setRival] = useState<string | null>(null);

  // Todas las series de la pantalla viven en `competidores-series.ts` como
  // funciones puras; aquí solo se les pasa el estado.
  const series = useCompetidoresView({
    competitors: data?.competitors,
    heatmapCcaa: data?.heatmap_ccaa,
    estacionalidad: data?.estacionalidad,
    totalAdjudicaciones: data?.total_adjudicaciones ?? null,
    totalEmpresas: data?.total_empresas ?? null,
    search,
    sortKey,
    sortDir,
    metrica,
    lente,
    seleccion,
    perfilCerrado,
    rival,
    vigiladas,
  });

  // Grupo de identidades del maestro que representan al mismo competidor
  // analítico (mismo nombre/NIF conectado, aún sin fusionar).
  const abierta = series.abierta;
  const perfilIds = useMemo(() => drillDownIds(abierta), [abierta]);
  const perfilId = perfilIds[0];
  const perfilParams = useMemo(() => drillDownExtraParams(perfilIds), [perfilIds]);

  // Sin `keepPreviousData` (último argumento) a propósito: el perfil lleva el
  // nombre de la empresa en la cabecera, y servir las cifras de la anterior
  // mientras carga la nueva sería el mismo encabezado sobre dos empresas.
  const {
    data: perfil,
    isLoading: perfilLoading,
    error: perfilError,
    refetch: refetchPerfil,
  } = useFilteredQuery<CompanyProfileData>(
    ["competitive-company-profile", String(perfilId ?? "none"), perfilIds.join(",")],
    `/api/v1/competitive/empresas/${perfilId ?? 0}/perfil`,
    { enabled: perfilId != null, staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
    perfilParams,
    true,
  );

  const abrirEmpresa = useCallback((nombre: string) => {
    setSeleccion(nombre);
    setPerfilCerrado(false);
  }, []);

  /** Elegir rival; pulsar la misma otra vez la quita del cara a cara. */
  const compararCon = useCallback((nombre: string) => {
    setRival((actual) => (actual === nombre ? null : nombre));
  }, []);

  return {
    data,
    isLoading,
    error,
    /** El «Reintentar» del error. */
    refetch: () => void refetch(),
    series,
    vigiladas,
    search,
    setSearch,
    metrica,
    setMetrica,
    lente,
    setLente,
    activeCcaa,
    toggleCcaa,
    sortKey,
    sortDir,
    toggleSort,
    abrirEmpresa,
    cerrarPerfil: () => setPerfilCerrado(true),
    compararCon,
    quitarRival: () => setRival(null),
    perfilId,
    perfilIds,
    perfil,
    perfilLoading,
    /** El fallo del perfil: se dice en el perfil, no como «sin datos». */
    perfilError,
    refetchPerfil: () => void refetchPerfil(),
  };
}
