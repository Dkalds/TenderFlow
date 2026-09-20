"use client";

import { useCallback, useMemo, useState } from "react";
import type {
  PaginationState,
  RowSelectionState,
  SortingState,
} from "@tanstack/react-table";
import type { LicitacionSummary } from "@/lib/api-types";
import {
  PAGE_SIZE,
  type MergedRow,
  type ScoringItem,
  type ScoringResponse,
  buildQueryParams,
  buildScoreMap,
  isClientSorted,
  mergeRows,
  nextSorting,
  pageWindowFor,
  toggleAllPageSelection,
  toggleRowSelection,
  totalPagesFor,
} from "./detalle-table-model";

/**
 * Estado de la tabla de Detalle: los dos hooks que le añaden React al modelo
 * puro de `detalle-table-model.ts`.
 *
 * La página sigue siendo la dueña de las queries: estos hooks no llaman a la
 * red, reciben lo ya descargado.
 */

export interface DetalleTableState {
  sorting: SortingState;
  setSorting: React.Dispatch<React.SetStateAction<SortingState>>;
  pagination: PaginationState;
  setPagination: React.Dispatch<React.SetStateAction<PaginationState>>;
  rowSelection: RowSelectionState;
  setRowSelection: React.Dispatch<React.SetStateAction<RowSelectionState>>;
  queryParams: Record<string, string>;
  /** Páginas con cursor conocido: las ya vistas más, si la hay, la siguiente. */
  alcanzables: number;
  /** Apunta el cursor de la página siguiente a `pageIndex` al leerla. */
  registrarSiguiente: (pageIndex: number, siguiente: string | null | undefined) => void;
  /** Cambia de página sólo si su cursor ya se conoce. */
  irAPagina: (pageIndex: number) => void;
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

  // Paginación por cursor (RFC 2026-09-06): `cursores[i]` es el cursor que
  // pide la página `i` (`null` para la primera). Se aprenden al leer cada
  // página (`registrarSiguiente`), así que se puede volver a cualquiera ya
  // vista o avanzar una, pero no saltar a la 40 sin pasar por la 39.
  const [cursores, setCursores] = useState<(string | null)[]>([null]);

  // Un cursor sólo vale para el orden y los filtros con los que se emitió:
  // cualquier cambio de los dos (o del tamaño de página) vuelve a la primera
  // y olvida los aprendidos. Mismo patrón de ajuste durante el render que el
  // de `q`, por la misma razón.
  const claveListado = JSON.stringify([filterParams, sorting, pagination.pageSize]);
  const [prevClave, setPrevClave] = useState(claveListado);
  if (claveListado !== prevClave) {
    setPrevClave(claveListado);
    setCursores([null]);
    if (pagination.pageIndex !== 0) setPagination({ ...pagination, pageIndex: 0 });
  }

  const cursor = cursores[pagination.pageIndex] ?? null;
  const queryParams = useMemo(
    () => buildQueryParams({ filterParams, pagination, sorting, cursor }),
    [filterParams, pagination, sorting, cursor],
  );

  const registrarSiguiente = useCallback(
    (pageIndex: number, siguiente: string | null | undefined) =>
      setCursores((actuales) =>
        siguiente && actuales.length === pageIndex + 1 ? [...actuales, siguiente] : actuales,
      ),
    [],
  );

  const alcanzables = cursores.length;
  const irAPagina = useCallback(
    (pageIndex: number) => {
      if (pageIndex < 0 || pageIndex >= alcanzables) return;
      setPagination((actual) => ({ ...actual, pageIndex }));
    },
    [alcanzables],
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
    alcanzables,
    registrarSiguiente,
    irAPagina,
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
  alcanzables,
  setRowSelection,
}: {
  items: LicitacionSummary[] | undefined;
  total: number | null | undefined;
  scoring: ScoringResponse | undefined | null;
  lastViewed: number;
  activeSort?: SortingState[number];
  pagination: PaginationState;
  rowSelection: RowSelectionState;
  /** Páginas con cursor conocido (ver `useDetalleTableState`); sin él, todas. */
  alcanzables?: number;
  setRowSelection: React.Dispatch<React.SetStateAction<RowSelectionState>>;
}): DetalleRows {
  const scoreMap = useMemo(() => buildScoreMap(scoring), [scoring]);

  const mergedRows = useMemo(
    () => mergeRows({ items: items ?? [], scoreMap, lastViewed, activeSort }),
    [items, scoreMap, lastViewed, activeSort],
  );

  const totalPages = totalPagesFor(total ?? 0, pagination.pageSize);
  const pageWindow = useMemo(
    () => pageWindowFor(pagination.pageIndex, totalPages, alcanzables ?? totalPages),
    [pagination.pageIndex, totalPages, alcanzables],
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
