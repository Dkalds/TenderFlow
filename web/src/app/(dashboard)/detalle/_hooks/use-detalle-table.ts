/**
 * Lógica de la tabla de Detalle, fuera del árbol de render.
 *
 * `detalle/page.tsx` pasaba de las 1.000 líneas y toda su lógica —parámetros de
 * consulta, mezcla de scoring, ciclo de orden, selección, ventana de paginación,
 * CSV— vivía dentro del componente. Testearla exigía montar la página entera:
 * lento, frágil y dependiente de trece componentes de UI que no aportan nada a
 * lo que se quiere verificar. Aquí quedan las funciones puras (testeables sin
 * React) y dos hooks finos que solo les añaden estado y memoización.
 *
 * La página sigue siendo la dueña de las queries: estos hooks no llaman a la
 * red, reciben lo ya descargado. Eso mantiene el invariante de `web/` —los datos
 * vienen de `api/` por HTTP— y hace que el test no necesite servidor.
 */
"use client";

import { useCallback, useMemo, useState } from "react";
import type {
  PaginationState,
  RowSelectionState,
  SortingState,
} from "@tanstack/react-table";
import type { LicitacionSummary } from "@/lib/api-types";

export const PAGE_SIZE = 25;

/**
 * Columnas que el backend sabe ordenar, y el valor de `sort` que espera.
 *
 * `GET /licitaciones` acepta `sort` con seis valores (`db/repositories/
 * licitaciones.py::_SORT_MAP`) y **descarta en silencio cualquier otro**. Las
 * tres de aquí se ordenan en servidor sobre el total; el resto se ordena en
 * cliente sobre la página cargada, y la tabla lo dice en vez de fingir un orden
 * global.
 */
export const SERVER_SORT: Record<string, string> = {
  titulo: "titulo",
  importe: "importe",
  fecha_publicacion: "fecha_publicacion",
};

export interface ScoringItem {
  id_externo: string;
  score: number;
  band: string;
  desglose: Record<string, number>;
}

export interface ScoringResponse {
  opportunities: ScoringItem[];
}

export interface MergedRow extends LicitacionSummary {
  score?: number;
  band?: string;
  desglose?: Record<string, number>;
  isNew?: boolean;
}

/* ── Funciones puras ────────────────────────────────────────────────── */

/**
 * Query string de `GET /licitaciones` para la página y el orden actuales.
 *
 * El prefijo `-` invierte el sentido por defecto de cada columna: para fecha el
 * default es descendente y para importe/título ascendente. Una columna que el
 * backend no sabe ordenar no añade `sort` — se ordenará en cliente.
 */
export function buildQueryParams({
  filterParams,
  pagination,
  sorting,
}: {
  filterParams: Record<string, string>;
  pagination: PaginationState;
  sorting: SortingState;
}): Record<string, string> {
  const params: Record<string, string> = {
    ...filterParams,
    limit: String(pagination.pageSize),
    offset: String(pagination.pageIndex * pagination.pageSize),
  };
  const active = sorting[0];
  const serverKey = active ? SERVER_SORT[active.id] : undefined;
  if (active && serverKey) {
    const defaultIsDesc = serverKey === "fecha_publicacion";
    params.sort = active.desc === defaultIsDesc ? serverKey : `-${serverKey}`;
  }
  return params;
}

/** Índice `id_externo → score` de la respuesta de scoring. */
export function buildScoreMap(
  scoring: ScoringResponse | undefined | null,
): Map<string, ScoringItem> {
  const map = new Map<string, ScoringItem>();
  for (const item of scoring?.opportunities ?? []) map.set(item.id_externo, item);
  return map;
}

/**
 * Filas de la página con su score y la marca de «nueva», ordenadas en cliente
 * solo si la columna activa no la sabe ordenar el backend.
 */
export function mergeRows({
  items,
  scoreMap,
  lastViewed,
  activeSort,
}: {
  items: LicitacionSummary[];
  scoreMap: Map<string, ScoringItem>;
  lastViewed: number;
  activeSort?: SortingState[number];
}): MergedRow[] {
  const rows: MergedRow[] = items.map((row) => {
    const scored = scoreMap.get(row.id_externo);
    const published = row.fecha_publicacion ? new Date(row.fecha_publicacion).getTime() : 0;
    return {
      ...row,
      score: scored?.score,
      band: scored?.band,
      desglose: scored?.desglose,
      isNew: published > lastViewed,
    };
  });

  if (!activeSort || SERVER_SORT[activeSort.id]) return rows;

  const key = activeSort.id as keyof MergedRow;
  return rows.sort((a, b) => {
    const left = a[key];
    const right = b[key];
    if (left == null && right == null) return 0;
    if (left == null) return 1;
    if (right == null) return -1;
    const compared =
      typeof left === "number" && typeof right === "number"
        ? left - right
        : String(left).localeCompare(String(right), "es", { sensitivity: "base" });
    return activeSort.desc ? -compared : compared;
  });
}

/** ¿El orden activo es de cliente (sobre la página cargada) y no global? */
export function isClientSorted(sorting: SortingState): boolean {
  const active = sorting[0];
  return Boolean(active && !SERVER_SORT[active.id]);
}

/** Ciclo de la cabecera: asc → desc → sin orden. */
export function nextSorting(current: SortingState, columnId: string): SortingState {
  const active = current[0];
  if (!active || active.id !== columnId) return [{ id: columnId, desc: false }];
  if (!active.desc) return [{ id: columnId, desc: true }];
  return [];
}

/** Alterna una fila en la selección (ausencia = no seleccionada). */
export function toggleRowSelection(
  current: RowSelectionState,
  id: string,
): RowSelectionState {
  const next = { ...current };
  if (next[id]) delete next[id];
  else next[id] = true;
  return next;
}

/** Marca o desmarca de golpe las filas de la página visible. */
export function toggleAllPageSelection(
  current: RowSelectionState,
  rows: MergedRow[],
  allSelected: boolean,
): RowSelectionState {
  const next = { ...current };
  for (const row of rows) {
    if (allSelected) delete next[row.id_externo];
    else next[row.id_externo] = true;
  }
  return next;
}

/** Ventana de ±2 páginas alrededor de la actual, recortada a los extremos. */
export function pageWindowFor(pageIndex: number, totalPages: number): number[] {
  const pages: number[] = [];
  const start = Math.max(0, pageIndex - 2);
  const end = Math.min(totalPages - 1, pageIndex + 2);
  for (let index = start; index <= end; index += 1) pages.push(index);
  return pages;
}

export const CSV_HEADERS = [
  "id_externo",
  "titulo",
  "organo_contratacion",
  "importe",
  "estado",
  "fecha_publicacion",
  "ccaa",
  "cpv",
  "tecnologia",
] as const;

/** CSV de las filas exportadas, con comillas escapadas al estilo RFC 4180. */
export function buildCsv(rows: LicitacionSummary[]): string {
  return [
    CSV_HEADERS.join(","),
    ...rows.map((row) =>
      CSV_HEADERS.map((header) => {
        const value = (row as unknown as Record<string, unknown>)[header];
        const text = value == null ? "" : String(value);
        return text.includes(",") || text.includes('"')
          ? `"${text.replace(/"/g, '""')}"`
          : text;
      }).join(","),
    ),
  ].join("\n");
}

/** `id_externo` de las filas visibles — es lo que se pide al endpoint de scoring. */
export function pageIdsOf(items: LicitacionSummary[] | undefined): string[] {
  return (items ?? []).map((row) => row.id_externo).filter(Boolean);
}

/** Número de páginas para un total dado (nunca menos de una). */
export function totalPagesFor(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / pageSize));
}

/* ── Hooks ──────────────────────────────────────────────────────────── */

export interface DetalleTableState {
  sorting: SortingState;
  setSorting: React.Dispatch<React.SetStateAction<SortingState>>;
  pagination: PaginationState;
  setPagination: React.Dispatch<React.SetStateAction<PaginationState>>;
  rowSelection: RowSelectionState;
  setRowSelection: React.Dispatch<React.SetStateAction<RowSelectionState>>;
  queryParams: Record<string, string>;
  activeSort?: SortingState[number];
  clientSorted: boolean;
  toggleSort: (columnId: string) => void;
  toggleRow: (id: string) => void;
}

/**
 * Estado de la tabla (orden, página, selección) y los parámetros de consulta que
 * se derivan de él.
 *
 * `q` entra como dependencia porque cambiar la búsqueda global vuelve a la
 * primera página: «página 7 de otro criterio» no significa nada.
 */
export function useDetalleTableState({
  filterParams,
  q,
  pageSize = PAGE_SIZE,
}: {
  filterParams: Record<string, string>;
  q: string;
  pageSize?: number;
}): DetalleTableState {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize,
  });
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});

  // Al cambiar la búsqueda global se vuelve a la primera página: «página 7 de
  // otro criterio» no significa nada. El ajuste va durante el render y no en un
  // efecto —el patrón que React documenta para derivar estado de una prop—, así
  // que React descarta este render y repite con `pageIndex: 0` antes de commit,
  // en vez de pintar y luego corregir.
  const [prevQ, setPrevQ] = useState(q);
  if (q !== prevQ) {
    setPrevQ(q);
    if (pagination.pageIndex !== 0) setPagination({ ...pagination, pageIndex: 0 });
  }

  const queryParams = useMemo(
    () => buildQueryParams({ filterParams, pagination, sorting }),
    [filterParams, pagination, sorting],
  );

  const toggleSort = useCallback(
    (columnId: string) => setSorting((current) => nextSorting(current, columnId)),
    [],
  );

  const toggleRow = useCallback(
    (id: string) => setRowSelection((current) => toggleRowSelection(current, id)),
    [],
  );

  return {
    sorting,
    setSorting,
    pagination,
    setPagination,
    rowSelection,
    setRowSelection,
    queryParams,
    activeSort: sorting[0],
    clientSorted: isClientSorted(sorting),
    toggleSort,
    toggleRow,
  };
}

export interface DetalleRows {
  scoreMap: Map<string, ScoringItem>;
  mergedRows: MergedRow[];
  totalPages: number;
  pageWindow: number[];
  selectedIds: string[];
  selectedItems: MergedRow[];
  allPageSelected: boolean;
  toggleAllPage: () => void;
}

/** Derivaciones sobre la página descargada: scoring, orden cliente, selección. */
export function useDetalleRows({
  items,
  total,
  scoring,
  lastViewed,
  activeSort,
  pagination,
  rowSelection,
  setRowSelection,
}: {
  items: LicitacionSummary[] | undefined;
  total: number | undefined;
  scoring: ScoringResponse | undefined | null;
  lastViewed: number;
  activeSort?: SortingState[number];
  pagination: PaginationState;
  rowSelection: RowSelectionState;
  setRowSelection: React.Dispatch<React.SetStateAction<RowSelectionState>>;
}): DetalleRows {
  const scoreMap = useMemo(() => buildScoreMap(scoring), [scoring]);

  const mergedRows = useMemo(
    () => mergeRows({ items: items ?? [], scoreMap, lastViewed, activeSort }),
    [items, scoreMap, lastViewed, activeSort],
  );

  const totalPages = totalPagesFor(total ?? 0, pagination.pageSize);
  const pageWindow = useMemo(
    () => pageWindowFor(pagination.pageIndex, totalPages),
    [pagination.pageIndex, totalPages],
  );

  const selectedIds = useMemo(
    () => Object.keys(rowSelection).filter((key) => rowSelection[key]),
    [rowSelection],
  );
  const selectedItems = useMemo(
    () => mergedRows.filter((row) => selectedIds.includes(row.id_externo)),
    [mergedRows, selectedIds],
  );
  const allPageSelected =
    mergedRows.length > 0 && mergedRows.every((row) => rowSelection[row.id_externo]);

  const toggleAllPage = useCallback(
    () =>
      setRowSelection((current) => toggleAllPageSelection(current, mergedRows, allPageSelected)),
    [mergedRows, allPageSelected, setRowSelection],
  );

  return {
    scoreMap,
    mergedRows,
    totalPages,
    pageWindow,
    selectedIds,
    selectedItems,
    allPageSelected,
    toggleAllPage,
  };
}
