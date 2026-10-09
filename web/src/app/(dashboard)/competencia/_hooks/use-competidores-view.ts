"use client";

/**
 * Agregador de las series de Competidores.
 *
 * Memoiza en un solo sitio, sobre los datos ya descargados, todo lo que la
 * pantalla dibuja. Las reglas de cada serie viven en `competidores-series.ts`
 * y `competidores-cruces.ts`, y las de la tabla en `competidores-tabla.ts`, ambas como funciones puras.
 *
 * Aquí está la única decisión de cableado que importa: **la búsqueda filtra el
 * ranking, el mapa y la matriz, pero no el titular ni el reparto**. Esos dos
 * hablan del mercado; buscar «beta» no convierte a Beta en el 100 % de él.
 *
 * No hay fetch: eso es `use-competidores-data.ts`.
 */

import { useMemo } from "react";

import { buildHeatmap, buildMapa, type HeatmapModel, type MapaModel } from "./competidores-cruces";
import {
  buildConcentracion,
  buildDuelo,
  buildEstacionalidad,
  buildReparto,
  ordenarPorMetrica,
  resolverAbierta,
  resolverRival,
  type Concentracion,
  type EstacionalidadPoint,
  type FilaDuelo,
  type TramoReparto,
} from "./competidores-series";
import { filterBySearch, sortCompetitors } from "./competidores-tabla";
import type {
  Competitor,
  EstacionalidadEntry,
  HeatmapEntry,
  Lente,
  Metrica,
  SortKey,
} from "./competidores-types";

export interface CompetidoresViewInput {
  competitors: Competitor[] | undefined;
  heatmapCcaa: HeatmapEntry[] | undefined;
  estacionalidad: EstacionalidadEntry[] | undefined;
  totalAdjudicaciones: number | null;
  totalEmpresas: number | null;
  search: string;
  sortKey: SortKey;
  sortDir: "asc" | "desc";
  metrica: Metrica;
  lente: Lente;
  /** Empresa elegida para el perfil; `null` = la primera del ranking. */
  seleccion: string | null;
  perfilCerrado: boolean;
  /** Empresa elegida para el cara a cara. */
  rival: string | null;
  /** Ids del maestro de las empresas que vigilas. */
  vigiladas: ReadonlySet<number>;
}

export interface CompetidoresView {
  /** Lo que queda tras la búsqueda, ordenado por la medida activa. */
  ordenados: Competitor[];
  /** Lo mismo, con el orden de columna de la tabla completa. */
  tabla: Competitor[];
  concentracion: Concentracion;
  reparto: TramoReparto[];
  mapa: MapaModel;
  heatmap: HeatmapModel;
  meses: EstacionalidadPoint[];
  abierta: Competitor | null;
  /** Posición de la abierta en el ranking por la medida activa, desde 1. */
  rangoAbierta: number | null;
  rival: Competitor | null;
  duelo: FilaDuelo[] | null;
}

const SIN_COMPETIDORES: Competitor[] = [];

/** Todas las series de la pantalla, memoizadas sobre los datos ya descargados. */
export function useCompetidoresView({
  competitors,
  heatmapCcaa,
  estacionalidad,
  totalAdjudicaciones,
  totalEmpresas,
  search,
  sortKey,
  sortDir,
  metrica,
  lente,
  seleccion,
  perfilCerrado,
  rival: rivalElegido,
  vigiladas,
}: CompetidoresViewInput): CompetidoresView {
  const todos = competitors ?? SIN_COMPETIDORES;
  const totales = useMemo(
    () => ({ totalAdjudicaciones, totalEmpresas }),
    [totalAdjudicaciones, totalEmpresas],
  );

  const filtrados = useMemo(() => filterBySearch(todos, search), [todos, search]);
  const ordenados = useMemo(() => ordenarPorMetrica(filtrados, metrica), [filtrados, metrica]);
  const tabla = useMemo(() => sortCompetitors(filtrados, sortKey, sortDir), [filtrados, sortKey, sortDir]);

  const abierta = useMemo(
    () => resolverAbierta(ordenados, seleccion, perfilCerrado),
    [ordenados, seleccion, perfilCerrado],
  );
  const rangoAbierta = abierta ? ordenados.indexOf(abierta) + 1 : null;
  const rival = useMemo(() => resolverRival(todos, rivalElegido, abierta), [todos, rivalElegido, abierta]);

  const concentracion = useMemo(() => buildConcentracion(todos, metrica, totales), [todos, metrica, totales]);
  const reparto = useMemo(
    () => buildReparto(todos, metrica, totales, abierta?.nombre ?? null),
    [todos, metrica, totales, abierta],
  );

  const mapa = useMemo(
    () => buildMapa(filtrados, lente, { abierta: abierta?.nombre ?? null, vigiladas }),
    [filtrados, lente, abierta, vigiladas],
  );
  const heatmap = useMemo(() => buildHeatmap(heatmapCcaa, search), [heatmapCcaa, search]);
  const meses = useMemo(() => buildEstacionalidad(estacionalidad), [estacionalidad]);
  const duelo = useMemo(() => (abierta && rival ? buildDuelo(abierta, rival) : null), [abierta, rival]);

  return {
    ordenados,
    tabla,
    concentracion,
    reparto,
    mapa,
    heatmap,
    meses,
    abierta,
    rangoAbierta,
    rival,
    duelo,
  };
}
